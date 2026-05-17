"""
Kerros 1b: OpenAI Privacy Filter (huggingface.co/openai/privacy-filter)

Bidirektionaalinen token-luokittelumalli PII-tunnistukseen.
Toimii Presidion rinnalla - erityisen hyvä englanninkielisille teksteille
ja kontekstuaaliselle tunnistukselle.

Malli: openai/privacy-filter (Apache 2.0)
Koko: 1.5B parametria, 50M aktiivista
Tarkkuus: 96% F1 (PII-Masking-300k benchmark)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OpenAIFilterMatch:
    value: str
    pii_type: str
    confidence: float
    start: int
    end: int


# Singleton - ladataan kerran
_tokenizer = None
_model = None
_pipeline = None
_loaded: bool = False


# OpenAI Privacy Filter -kategorioiden mappaus meidän tyyppeihin
_LABEL_MAP = {
    "PRIVATE_NAME":    "PERSON",
    "CONTACT_INFO":    "PHONE_NUMBER",
    "DIGITAL_ID":      "EMAIL_ADDRESS",
    "SECRETS":         "CUSTOM",
    "ORGANIZATION":    "ORGANIZATION",
    "LOCATION":        "LOCATION",
    "DATE":            "DATE_TIME",
    "FINANCIAL":       "CUSTOM",
}


def _load_model():
    """Lazy-lataus: ladataan malli ensimmäistä kertaa käytettäessä."""
    global _tokenizer, _model, _pipeline, _loaded

    if _loaded:
        return _pipeline

    try:
        from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification

        logger.info("Ladataan OpenAI Privacy Filter -malli...")

        _tokenizer = AutoTokenizer.from_pretrained("openai/privacy-filter")
        _model = AutoModelForTokenClassification.from_pretrained("openai/privacy-filter")

        _pipeline = pipeline(
            "token-classification",
            model=_model,
            tokenizer=_tokenizer,
            aggregation_strategy="simple",  # Yhdistää peräkkäiset token-osumat
            device=-1,  # CPU (-1), GPU (0) jos saatavilla
        )

        logger.info("OpenAI Privacy Filter ladattu onnistuneesti")
        _loaded = True
        return _pipeline

    except Exception as e:
        logger.warning(f"OpenAI Privacy Filter -lataus epäonnistui: {e}")
        _loaded = True  # Merkitään ladatuksi jotta ei yritetä uudelleen
        return None


def find_pii_openai(text: str) -> list[OpenAIFilterMatch]:
    """
    Tunnistaa PII:t OpenAI Privacy Filter -mallilla.

    Args:
        text: Analysoitava teksti

    Returns:
        Lista löydetyistä PII-arvoista
    """
    pipe = _load_model()
    if pipe is None:
        logger.debug("OpenAI Privacy Filter ei käytettävissä")
        return []

    try:
        # Malli tukee 128k token konteksti-ikkunaa
        # Mutta käytännössä jaetaan pitkät tekstit palasiin
        max_chars = 4000
        matches = []

        # Käsitellään teksti palasissa jos pitkä
        chunks = _split_text(text, max_chars)

        for chunk_text, chunk_offset in chunks:
            results = pipe(chunk_text)

            for result in results:
                # Suodatetaan heikot osumat
                if result["score"] < 0.7:
                    continue

                value = result["word"].strip()

                # Suodatetaan liian lyhyet
                if len(value) < 3:
                    continue

                # Puhdistetaan tokenizer-artefaktit (## etuliitteet)
                value = value.replace("##", "").strip()
                if not value:
                    continue

                pii_type = _LABEL_MAP.get(result["entity_group"], "CUSTOM")

                matches.append(OpenAIFilterMatch(
                    value=value,
                    pii_type=pii_type,
                    confidence=float(result["score"]),
                    start=result["start"] + chunk_offset,
                    end=result["end"] + chunk_offset,
                ))

        logger.info(f"OpenAI Privacy Filter löysi {len(matches)} PII-arvoa")
        return matches

    except Exception as e:
        logger.error(f"OpenAI Privacy Filter -analyysi epäonnistui: {e}")
        return []


def _split_text(text: str, max_chars: int) -> list[tuple[str, int]]:
    """
    Jakaa pitkän tekstin palasiin säilyttäen offset-tiedon.
    Jakaa lauseiden kohdalta jos mahdollista.
    """
    if len(text) <= max_chars:
        return [(text, 0)]

    chunks = []
    offset = 0

    while offset < len(text):
        chunk = text[offset:offset + max_chars]

        # Yritetään jakaa lauseen lopusta
        if offset + max_chars < len(text):
            last_period = chunk.rfind(". ")
            last_newline = chunk.rfind("\n")
            split_at = max(last_period, last_newline)

            if split_at > max_chars // 2:
                chunk = chunk[:split_at + 1]

        chunks.append((chunk, offset))
        offset += len(chunk)

    return chunks
