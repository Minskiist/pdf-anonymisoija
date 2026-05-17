"""
Kerros 1: Microsoft Presidio.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PresidioMatch:
    value: str
    pii_type: str
    confidence: float
    start: int
    end: int
    language: str


def _load_analyzer():
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "en", "model_name": "en_core_web_lg"},
                {"lang_code": "fi", "model_name": "fi_core_news_lg"},
            ],
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["fi", "en"])
        logger.info("Presidio AnalyzerEngine ladattu onnistuneesti")
        return analyzer
    except ImportError as e:
        logger.warning(f"Presidio ei asennettu: {e}.")
        return None
    except Exception as e:
        logger.warning(f"Presidio-alustus epaonnistui: {e}.")
        return None


_analyzer: Optional[object] = None
_analyzer_loaded: bool = False


def _get_analyzer():
    global _analyzer, _analyzer_loaded
    if not _analyzer_loaded:
        _analyzer = _load_analyzer()
        _analyzer_loaded = True
    return _analyzer


PRESIDIO_ENTITIES = [
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "IBAN_CODE",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "NRP",
    "AGE",
    "URL",
]

_JOB_TITLES = {
    "ceo", "cto", "coo", "cfo", "cpo", "ciso",
    "manager", "director", "lead", "engineer", "analyst",
    "consultant", "developer", "designer", "architect",
    "president", "chairman", "founder", "partner",
    "toimitusjohtaja", "johtaja", "paallikkö", "asiantuntija",
}


def _is_job_title(value: str) -> bool:
    words = value.lower().split()
    if len(words) == 1 and words[0] in _JOB_TITLES:
        return True
    if len(words) > 3:
        return True
    return False


def find_pii_presidio(text: str, language: str = "fi") -> list[PresidioMatch]:
    analyzer = _get_analyzer()
    if analyzer is None:
        return []
    try:
        results = analyzer.analyze(text=text, language=language, entities=PRESIDIO_ENTITIES, score_threshold=0.75)
        matches = []
        for result in results:
            value = text[result.start:result.end]
            if result.entity_type == "ORGANIZATION" and _is_job_title(value):
                continue
            # Suodatetaan liian lyhyet arvot pois
            if len(value.strip()) < 3:
                continue
            matches.append(PresidioMatch(value=value, pii_type=result.entity_type, confidence=float(result.score), start=result.start, end=result.end, language=language))
        return matches
    except Exception as e:
        logger.error(f"Presidio-analyysi epaonnistui: {e}")
        return []


def find_pii_presidio_entities(text: str, language: str, entities: list[str]) -> list[PresidioMatch]:
    analyzer = _get_analyzer()
    if analyzer is None:
        return []
    try:
        results = analyzer.analyze(text=text, language=language, entities=entities, score_threshold=0.75)
        return [PresidioMatch(value=text[r.start:r.end], pii_type=r.entity_type, confidence=float(r.score), start=r.start, end=r.end, language=language) for r in results if not _is_job_title(text[r.start:r.end])]
    except Exception as e:
        logger.error(f"Presidio-analyysi epaonnistui: {e}")
        return []


def detect_language(text: str) -> str:
    finnish_indicators = [
        "ja", "on", "ei", "ole", "tai", "myos", "seka",
        "kuitenkin", "joka", "jolle", "jonka", "joten", "koska",
        "sopimus", "asiakas", "toimitus", "maksu", "lasku",
    ]
    words = text.lower().split()
    fi_count = sum(1 for w in words[:100] if w in finnish_indicators)
    return "fi" if fi_count > 8 else "en"
