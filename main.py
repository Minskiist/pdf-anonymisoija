import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from backend.config import settings
from backend.pdf.parser import extract_text
from backend.pdf.generator import generate_pdf
from backend.pii.engine import analyze_text, add_manual_pii
from backend.session import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

async def _cleanup_loop():
    while True:
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
        removed = store.cleanup_expired_sessions()
        if removed:
            logger.info(f"Siivous: poistettu {removed} sessiota")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Kaynnistetaan {settings.app_name} v{settings.app_version}")
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()

app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173","http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class AddMappingRequest(BaseModel):
    session_id: str
    value: str
    pii_type: str = "CUSTOM"

class RemoveMappingRequest(BaseModel):
    session_id: str
    value: str

class DeanonymizeRequest(BaseModel):
    session_id: str
    llm_response: str

class ConfirmMappingRequest(BaseModel):
    session_id: str
    value: str
    confirmed: bool

_text_store: dict[str, str] = {}

def _store_text(session_id: str, text: str) -> None:
    _text_store[session_id] = text

def _load_text(session_id: str) -> str | None:
    return _text_store.get(session_id)

def _delete_text(session_id: str) -> None:
    _text_store.pop(session_id, None)

def _delete_all_texts() -> None:
    _text_store.clear()

@app.post("/api/analyze")
async def analyze_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".pdf", ".docx")):
        raise HTTPException(status_code=400, detail="Vain PDF-tiedostot ovat tuettuja.")
    pdf_bytes = await file.read()
    max_bytes = settings.max_pdf_size_mb * 1024 * 1024
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF on liian suuri. Maksimikoko: {settings.max_pdf_size_mb} MB.")
    try:
        parsed = extract_text(pdf_bytes, filename=file.filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"PDF:n purku epaonnistui: {e}")
    if not parsed.has_text_layer:
        return JSONResponse(status_code=422, content={"error": "ocr_required", "message": "Skannattu kuva. OCR tulossa."})
    result = await analyze_text(parsed.text)
    session_id = store.create_session(engine=result.engine, filename=file.filename, language=result.language)
    _store_text(session_id, parsed.text)
    mappings = [{"id": m.id, "value": m.original_value, "placeholder": m.placeholder, "type": m.pii_type, "type_code": m.type_code, "confidence": round(m.confidence, 2), "is_uncertain": m.is_uncertain, "source": m.source} for m in result.engine.get_all_mappings()]
    return {"session_id": session_id, "filename": file.filename, "page_count": parsed.page_count, "language": result.language, "total_found": result.total_found, "uncertain_count": result.uncertain_count, "sources": result.sources, "mappings": mappings, "has_text_layer": parsed.has_text_layer, "metadata": parsed.metadata}

@app.post("/api/anonymize")
async def anonymize_document(session_id: str = Form(...)):
    result = store.load_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, filename, language = result
    original_text = _load_text(session_id)
    if original_text is None:
        raise HTTPException(status_code=404, detail="Alkuperaista tekstia ei loydy.")
    anon_text, used_mappings = engine.anonymize(original_text)
    store.update_session(session_id, engine)
    return {"session_id": session_id, "anonymized_text": anon_text, "replacements_made": len(used_mappings), "filename": filename}

@app.post("/api/mapping/add")
async def add_mapping(req: AddMappingRequest):
    result = store.load_session(req.session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, filename, language = result
    if not req.value.strip():
        raise HTTPException(status_code=400, detail="Arvo ei voi olla tyhja.")
    mapping = add_manual_pii(engine, req.value, req.pii_type)
    store.update_session(req.session_id, engine)
    return {"success": True, "mapping": {"id": mapping.id, "value": mapping.original_value, "placeholder": mapping.placeholder, "type": mapping.pii_type, "type_code": mapping.type_code, "confidence": mapping.confidence, "is_uncertain": mapping.is_uncertain, "source": mapping.source}}

@app.post("/api/mapping/remove")
async def remove_mapping(req: RemoveMappingRequest):
    result = store.load_session(req.session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, _, _ = result
    removed = engine.remove_mapping(req.value)
    store.update_session(req.session_id, engine)
    return {"success": removed}

@app.post("/api/mapping/confirm")
async def confirm_mapping(req: ConfirmMappingRequest):
    result = store.load_session(req.session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, _, _ = result
    if not req.confirmed:
        engine.remove_mapping(req.value)
    else:
        mapping = engine._mappings.get(req.value.strip())
        if mapping:
            mapping.is_uncertain = False
    store.update_session(req.session_id, engine)
    return {"success": True}

@app.post("/api/deanonymize")
async def deanonymize(req: DeanonymizeRequest):
    result = store.load_session(req.session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, filename, _ = result
    deanon_text, not_found = engine.deanonymize(req.llm_response)
    return {"session_id": req.session_id, "deanonymized_text": deanon_text, "not_found_placeholders": not_found, "filename": filename}

@app.post("/api/deanonymize/pdf")
async def deanonymize_to_pdf(req: DeanonymizeRequest):
    result = store.load_session(req.session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, filename, _ = result
    deanon_text, not_found = engine.deanonymize(req.llm_response)
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    try:
        pdf_bytes = generate_pdf(deanon_text, title=f"{base_name} (kasitelty)")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{base_name}_deanonymisoitu.pdf"', "X-Not-Found-Placeholders": ",".join(not_found)})

@app.get("/api/sessions/{session_id}/text")
async def get_session_text(session_id: str):
    text = _load_text(session_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Tekstia ei loydy.")
    return {"text": text}

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    result = store.load_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    engine, filename, language = result
    mappings = [{"id": m.id, "value": m.original_value, "placeholder": m.placeholder, "type": m.pii_type, "type_code": m.type_code, "confidence": round(m.confidence, 2), "is_uncertain": m.is_uncertain, "source": m.source, "occurrences": m.occurrences} for m in engine.get_all_mappings()]
    return {"session_id": session_id, "filename": filename, "language": language, "mappings": mappings, "uncertain_count": len(engine.get_uncertain_mappings())}

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    _delete_text(session_id)
    deleted = store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sessiota ei loydy.")
    return {"success": True}

@app.delete("/api/sessions")
async def delete_all():
    count = store.delete_all_sessions()
    _delete_all_texts()
    return {"success": True, "deleted_count": count}

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.app_version, "ollama_url": settings.ollama_base_url, "model": settings.ollama_model}
