"""
Kerros 3: LLM (Qwen3:27b via Ollama).

Kaksi roolia:
  1. find_pii_llm    - Etsii uusia PII-arvoja joita Presidio/regex ei löytänyt
  2. validate_pii_llm - Validoi Presidion epävarmat löydökset kontekstin perusteella
"""

from __future__ import annotations

import json
import logging
import httpx
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMMatch:
    value: str
    pii_type: str
    confidence: float
    reasoning: str


# ---------------------------------------------------------------------------
# Promptit
# ---------------------------------------------------------------------------

_SYSTEM_FIND = """Olet tietosuoja-asiantuntija. Tehtäväsi on tunnistaa teksteistä arkaluonteiset henkilötiedot (PII).

Palauta AINOASTAAN JSON-muodossa löydetyt arvot. Ei muuta tekstiä, ei selityksiä, ei markdown-koodiblokeja.

Tunnista näitä tietoja jos niitä esiintyy:
- Henkilöiden nimet (etunimet, sukunimet, koko nimet)
- Yritysnimet ja organisaatiot (ei yleisiä ohjelmistoja kuten Canva, Zapier, Make)
- Osoitteet ja paikat
- Syntymäpäivät ja henkilökohtaiset päivämäärät
- Taloudelliset summat yhdistettynä henkilöihin tai yrityksiin
- Muut tunnistettavat henkilötiedot

EI pidä tunnistaa:
- Yleisiä ohjelmistoja tai palveluita (Canva, Make, Zapier, Midjourney, ChatGPT jne.)
- Ammattinimikkeitä
- Yleisiä teknisiä termejä tai lyhenteitä

Vastaa VAIN tässä JSON-muodossa:
{"found": [{"value": "löydetty arvo", "type": "PERSON|ORGANIZATION|ADDRESS|DATE|FINANCIAL|OTHER", "reasoning": "lyhyt perustelu"}]}

Jos mitään ei löydy: {"found": []}"""

_SYSTEM_VALIDATE = """Olet tietosuoja-asiantuntija. Tehtäväsi on arvioida onko annettu tekstinpätkä oikea henkilötieto (PII) vai ei.

Arvioi kontekstin perusteella. Palauta AINOASTAAN JSON. Ei muuta tekstiä, ei selityksiä, ei markdown-koodiblokeja.

Vastaa VAIN tässä JSON-muodossa:
{"is_pii": true/false, "reasoning": "lyhyt perustelu suomeksi"}

Esimerkkejä:
- "Minna Purkunen" kontekstissa "Palveluntarjoaja: Minna Purkunen" -> is_pii: true
- "Canva" kontekstissa "osaan käyttää Canvaa" -> is_pii: false
- "Make" kontekstissa "automatisoin Make-työkalulla" -> is_pii: false
- "ElevenLabs" kontekstissa "tuotan ääntä ElevenLabsilla" -> is_pii: false
- "Helsinki" kontekstissa "toimisto sijaitsee Helsingissä" -> is_pii: true (sijainti)
- "MRI" kontekstissa "19 vuoden MRI-kuvantamisen kokemus" -> is_pii: false (lyhenne/tekniikka)"""


# ---------------------------------------------------------------------------
# Apufunktio HTTP-kutsulle
# ---------------------------------------------------------------------------

async def _ollama_chat(system: str, user: str) -> str | None:
    """Tekee yhden Ollama-kutsun ja palauttaa vastauksen tekstinä."""
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 500,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")

    except httpx.ConnectError:
        logger.warning(f"Ollama ei vastaa osoitteessa {settings.ollama_base_url}.")
        return None
    except httpx.TimeoutException:
        logger.warning("Ollama-pyyntö aikakatkaistiin.")
        return None
    except Exception as e:
        logger.error(f"Ollama-kutsu epäonnistui: {e}")
        return None


def _parse_json(content: str) -> dict | None:
    """Parsii JSON vastauksen sisältä."""
    try:
        # Poistetaan mahdolliset markdown-koodiblokki-merkinnät
        content = content.replace("```json", "").replace("```", "").strip()
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start == -1:
            return None
        return json.loads(content[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Funktio 1: Uusien PII-arvojen etsintä
# ---------------------------------------------------------------------------

async def find_pii_llm(
    text: str,
    already_found: list[str],
    max_chars: int = 2000,
) -> list[LLMMatch]:
    """
    Pyytää Qwen3:27b:tä tunnistamaan loput PII-arvot
    joita Presidio tai regex ei löytänyt.
    """
    if not settings.use_llm_layer:
        return []

    text_chunk = text[:max_chars]
    already_str = ", ".join(f'"{v}"' for v in already_found[:20]) if already_found else "ei mitään"

    user_message = f"""Analysoi seuraava teksti ja tunnista siitä arkaluonteiset tiedot.

Jo löydetyt (ÄLÄ toista näitä): {already_str}

Teksti:
---
{text_chunk}
---"""

    content = await _ollama_chat(_SYSTEM_FIND, user_message)
    if content is None:
        return []

    parsed = _parse_json(content)
    if parsed is None:
        logger.error(f"LLM-vastauksen parsinta epäonnistui. Vastaus: {content[:200]}")
        return []

    found = parsed.get("found", [])
    already_lower = {v.lower() for v in already_found}
    matches = []

    pii_type_map = {
        "PERSON": "PERSON",
        "ORGANIZATION": "ORGANIZATION",
        "ADDRESS": "ADDRESS",
        "DATE": "DATE_TIME",
        "FINANCIAL": "CUSTOM",
        "OTHER": "CUSTOM",
    }

    for item in found:
        value = item.get("value", "").strip()
        if not value or len(value) < 3:
            continue
        if value.lower() in already_lower:
            continue

        matches.append(LLMMatch(
            value=value,
            pii_type=pii_type_map.get(item.get("type", "OTHER"), "CUSTOM"),
            confidence=0.7,
            reasoning=item.get("reasoning", ""),
        ))

    logger.info(f"LLM-kerros löysi {len(matches)} uutta PII-arvoa")
    return matches


# ---------------------------------------------------------------------------
# Funktio 2: Presidion löydösten validointi
# ---------------------------------------------------------------------------

async def validate_pii_llm(
    value: str,
    context: str,
    pii_type: str,
) -> bool:
    """
    Validoi yksittäisen Presidio-löydöksen kontekstin perusteella.

    Args:
        value: Tunnistettu arvo (esim. "Canva")
        context: Tekstipätkä arvon ympäriltä (esim. "...osaan käyttää Canvaa...")
        pii_type: Presidion antama tyyppi (esim. "ORGANIZATION")

    Returns:
        True = on oikea PII, False = ei ole PII
    """
    if not settings.use_llm_layer:
        return True  # Jos LLM ei käytössä, hyväksytään kaikki

    user_message = f"""Arvioi onko seuraava tunnistus oikea henkilötieto (PII).

Tunnistettu arvo: "{value}"
Tyyppi: {pii_type}
Konteksti: "{context}"

Onko tämä oikea PII joka pitää anonymisoida?"""

    content = await _ollama_chat(_SYSTEM_VALIDATE, user_message)
    if content is None:
        return True  # Jos Ollama ei vastaa, hyväksytään varmuuden vuoksi

    parsed = _parse_json(content)
    if parsed is None:
        logger.error(f"Validoinnin parsinta epäonnistui arvolle '{value}'")
        return True  # Epäselvässä tilanteessa hyväksytään

    is_pii = parsed.get("is_pii", True)
    reasoning = parsed.get("reasoning", "")
    logger.info(f"Validointi '{value}': is_pii={is_pii}, perustelu={reasoning}")
    return is_pii
