from __future__ import annotations
import logging
from dataclasses import dataclass
from backend.anonymizer.placeholder import PlaceholderEngine, PIIMapping
from backend.pii.presidio_layer import find_pii_presidio, find_pii_presidio_entities, detect_language
from backend.pii.regex_layer import find_pii_regex
from backend.pii.llm_layer import find_pii_llm

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
    sources: dict[str, int] = {"presidio": 0, "regex": 0, "llm": 0, "manual": 0}
    language = detect_language(text)
    logger.info(f"Tunnistettu kieli: {language}")
    for match in find_pii_regex(text):
        engine.add_mapping(original_value=match.value, pii_type=match.pii_type, confidence=match.confidence, source="regex")
        sources["regex"] += 1
    for match in find_pii_presidio(text, language=language):
        if not _already_covered(match.value, engine):
            engine.add_mapping(original_value=match.value, pii_type=match.pii_type, confidence=match.confidence, source="presidio")
            sources["presidio"] += 1
    for match in await find_pii_llm(text, already_found=[m.original_value for m in engine.get_all_mappings()]):
        if not _already_covered(match.value, engine):
            engine.add_mapping(original_value=match.value, pii_type=match.pii_type, confidence=match.confidence, source="llm", is_uncertain=True)
            sources["llm"] += 1
    all_mappings = engine.get_all_mappings()
    return PIIResult(engine=engine, language=language, total_found=len(all_mappings), uncertain_count=len(engine.get_uncertain_mappings()), sources=sources)

def add_manual_pii(engine: PlaceholderEngine, value: str, pii_type: str = "CUSTOM") -> PIIMapping:
    return engine.add_mapping(original_value=value, pii_type=pii_type, confidence=1.0, source="manual", is_uncertain=False)

def _already_covered(value: str, engine: PlaceholderEngine) -> bool:
    value_lower = value.lower().strip()
    for mapping in engine.get_all_mappings():
        mapped_lower = mapping.original_value.lower()
        if value_lower == mapped_lower:
            return True
        if value_lower in mapped_lower and len(value_lower) > 3:
            return True
    return False
