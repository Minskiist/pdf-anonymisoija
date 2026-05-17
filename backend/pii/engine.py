from __future__ import annotations
import logging
from dataclasses import dataclass
from backend.anonymizer.placeholder import PlaceholderEngine, PIIMapping
from backend.pii.presidio_layer import find_pii_presidio, detect_language
from backend.pii.regex_layer import find_pii_regex
from backend.pii.llm_layer import find_pii_llm
from backend.pii.openai_layer import find_pii_openai

logger = logging.getLogger(__name__)

@dataclass
class PIIResult:
    engine: PlaceholderEngine
    language: str
    total_found: int
    uncertain_count: int
    sources: dict[str, int]

async def analyze_text(text: str) -> PIIResult:
    engine = PlaceholderEngine()
    sources: dict[str, int] = {"presidio": 0, "regex": 0, "llm": 0, "openai": 0, "manual": 0}

    language = detect_language(text)
    logger.info(f"Tunnistettu kieli: {language}")

    # Kerros 2: Regex
    logger.info("Kerros 2: Regex...")
    for match in find_pii_regex(text):
        engine.add_mapping(original_value=match.value, pii_type=match.pii_type,
                           confidence=match.confidence, source="regex")
        sources["regex"] += 1
    logger.info(f"Regex loysi {sources['regex']} arvoa")

    # Kerros 1: Presidio
    logger.info(f"Kerros 1: Presidio ({language})...")
    for match in find_pii_presidio(text, language=language):
        if not _already_covered(match.value, engine):
            engine.add_mapping(original_value=match.value, pii_type=match.pii_type,
                               confidence=match.confidence, source="presidio")
            sources["presidio"] += 1
    logger.info(f"Presidio loysi {sources['presidio']} arvoa")

    # Kerros 1b: OpenAI Privacy Filter (vain englanninkielisille)
    logger.info("Kerros 1b: OpenAI Privacy Filter...")
    if language == "en":
        openai_matches = find_pii_openai(text)
    else:
        openai_matches = []
    for match in openai_matches:
        if not _already_covered(match.value, engine):
            engine.add_mapping(original_value=match.value, pii_type=match.pii_type,
                               confidence=match.confidence, source="openai")
            sources["openai"] += 1
    logger.info(f"OpenAI Filter loysi {sources['openai']} uutta arvoa")

    # Kerros 3: LLM
    logger.info("Kerros 3: LLM...")
    already_found = [m.original_value for m in engine.get_all_mappings()]
    for match in await find_pii_llm(text, already_found=already_found):
        if not _already_covered(match.value, engine):
            engine.add_mapping(original_value=match.value, pii_type=match.pii_type,
                               confidence=match.confidence, source="llm", is_uncertain=True)
            sources["llm"] += 1
    logger.info(f"LLM loysi {sources['llm']} uutta arvoa")

    all_mappings = engine.get_all_mappings()
    total = len(all_mappings)
    uncertain = len(engine.get_uncertain_mappings())
    logger.info(f"Valmis: {total} arvoa, {uncertain} epavarmaa, kieli={language}")

    return PIIResult(engine=engine, language=language, total_found=total,
                     uncertain_count=uncertain, sources=sources)

def add_manual_pii(engine: PlaceholderEngine, value: str, pii_type: str = "CUSTOM") -> PIIMapping:
    return engine.add_mapping(original_value=value, pii_type=pii_type,
                              confidence=1.0, source="manual", is_uncertain=False)

def _already_covered(value: str, engine: PlaceholderEngine) -> bool:
    value_lower = value.lower().strip()
    for mapping in engine.get_all_mappings():
        mapped_lower = mapping.original_value.lower()
        if value_lower == mapped_lower:
            return True
        if value_lower in mapped_lower and len(value_lower) > 3:
            return True
    return False
