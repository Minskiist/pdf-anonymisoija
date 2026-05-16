"""
PDF-parser – tekstin purku PyMuPDF:lla.

Tukee digitaalisia PDF:iä (tekstikerros olemassa).
OCR-hook on valmiina skannattuja dokumentteja varten (tuleva ominaisuus).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ParsedPDF:
    """Puretun PDF:n sisältö."""
    text: str                      # Koko teksti yhdistettynä
    pages: list[str]               # Sivut erikseen
    page_count: int
    filename: str
    has_text_layer: bool           # False = skannaus, tarvitsee OCR:n
    metadata: dict


def extract_text(pdf_bytes: bytes, filename: str = "document.pdf") -> ParsedPDF:
    """
    Purkaa tekstin PDF:stä.

    Args:
        pdf_bytes: PDF-tiedoston sisältö tavuina
        filename: Tiedostonimi (näytetään UI:ssa)

    Returns:
        ParsedPDF sisältäen tekstin ja metatiedot

    Raises:
        ValueError: Jos tiedosto ei ole kelvollinen PDF
        RuntimeError: Jos tekstin purku epäonnistuu
    """
    try:
        import fitz   # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "PyMuPDF ei ole asennettu. Asenna: pip install pymupdf"
        )

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"PDF:n avaaminen epäonnistui: {e}")

    page_texts: list[str] = []
    total_chars = 0

    for page_num in range(len(doc)):
        page = doc[page_num]

        # Ensin yritetään tekstikerrosta
        text = page.get_text("text")
        page_texts.append(text)
        total_chars += len(text.strip())

    has_text_layer = total_chars > 50   # Alle 50 merkkiä → todennäköisesti skannaus

    if not has_text_layer:
        logger.warning(
            f"PDF '{filename}' ei näytä sisältävän tekstikerrosta "
            f"({total_chars} merkkiä). Harkitse OCR-tunnistusta."
        )
        # OCR-hook: kun OCR otetaan käyttöön, kutsutaan tästä
        _ocr_hook_placeholder(filename)

    # Metatiedot
    meta = doc.metadata or {}
    metadata = {
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "creator": meta.get("creator", ""),
        "creation_date": meta.get("creationDate", ""),
    }

    doc.close()

    full_text = "\n\n--- Sivu {n} ---\n\n".join(page_texts)
    # Siistimpi versio sivuerottimella
    full_text = _join_pages(page_texts)

    return ParsedPDF(
        text=full_text,
        pages=page_texts,
        page_count=len(page_texts),
        filename=filename,
        has_text_layer=has_text_layer,
        metadata=metadata,
    )


def extract_text_from_path(path: Path) -> ParsedPDF:
    """Apufunktio tiedostopolusta lukemiseen (testaukseen)."""
    pdf_bytes = path.read_bytes()
    return extract_text(pdf_bytes, filename=path.name)


def _join_pages(pages: list[str]) -> str:
    """Yhdistää sivut selkeästi eroteltuina."""
    parts = []
    for i, page_text in enumerate(pages, start=1):
        if page_text.strip():
            parts.append(f"[Sivu {i}]\n{page_text.strip()}")
    return "\n\n".join(parts)


def _ocr_hook_placeholder(filename: str) -> None:
    """
    OCR-hook – kutsutaan kun tekstikerrosta ei löydy.

    TULEVA OMINAISUUS: Tähän lisätään Tesseract/EasyOCR integraatio.
    Nyt kirjataan varoitus käyttäjälle.
    """
    logger.info(
        f"OCR-hook aktivoitu tiedostolle '{filename}'. "
        "OCR-tunnistus ei ole vielä käytössä. "
        "Lisätään tulevassa versiossa."
    )
