"""
Kerros 3: LLM (Qwen3:27b via Ollama).

Käytetään vain epäselviin tapauksiin joita Presidio tai regex
eivät tunnistaneet varmuudella. Tämä pitää kustannukset (aika/resurssit) kurissa.

Strategia:
  1. Lähetetään Ollamalle tekstipätkä + jo löydetyt PII-arvot
  2. Pyydetään tunnistamaan loput arkaluonteiset tiedot
  3. Palautetaan uudet löydöt confidence=0.7 (merkitään epävarmoiksi)
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
    reasoning: str   # LLM:n perustelu – näytetään käyttäjälle epävarmoissa


# Prompt-pohja suomeksi ja englanniksi
_SYSTEM_PROMPT = """Olet tietosuoja-asiantuntija. Tehtäväsi on tunnistaa teksteistä arkaluonteiset henkilötiedot (PII) ja liiketoimintatiedot.

Palauta AINOASTAAN JSON-muodossa löydetyt arvot. Ei muuta tekstiä, ei selityksiä.

Tunnista näitä tietoja jos niitä esiintyy:
- Henkilöiden nimet (etunimet, sukunimet, koko nimet)
- Yritysnimet ja organisaatiot
- Osoitteet ja paikat
- Päivämäärät (erityisesti syntymäpäivät)
- Taloudelliset summat yhdistettynä henkilöihin tai yrityksiin
- Muut tunnistettavat henkilötiedot

Vastaa VAIN tässä JSON-muodossa:
{
  "found": [
    {"value": "löydetty arvo", "type": "PERSON|ORGANIZATION|ADDRESS|DATE|FINANCIAL|OTHER", "reasoning": "lyhyt perustelu"}
  ]
}

Jos mitään ei löydy: {"found": []}"""


async def find_pii_llm(
    text: str,
    already_found: list[str],
    max_chars: int = 2000,
) -> list[LLMMatch]:
    """
    Pyytää Qwen3:27b:tä tunnistamaan loput PII-arvot.

    Args:
        text: Analysoitava teksti (leikataan max_chars:iin)
        already_found: Jo tunnistetut arvot (ohitetaan duplikaatit)
        max_chars: Maksimi merkkimäärä per pyyntö

    Returns:
        Lista uusista PII-löydöistä
    """
    if not settings.use_llm_layer:
        return []

    # Leikataan teksti kohtuulliseen palaseen
    text_chunk = text[:max_chars]

    # Kerrotaan LLM:lle mitkä on jo löydetty
    already_str = ", ".join(f'"{v}"' for v in already_found[:20]) if already_found else "ei mitään"

    user_message = f"""Analysoi seuraava teksti ja tunnista siitä arkaluonteiset tiedot.

Jo löydetyt (ÄLÄ toista näitä): {already_str}

Teksti:
---
{text_chunk}
---"""

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,   # Matala lämpötila → deterministisempi
                        "num_predict": 500,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

    except httpx.ConnectError:
        logger.warning(f"Ollama ei vastaa osoitteessa {settings.ollama_base_url}. Ohitetaan LLM-kerros.")
        return []
    except httpx.TimeoutException:
        logger.warning("Ollama-pyyntö aikakatkaistiin. Ohitetaan LLM-kerros.")
        return []
    except Exception as e:
        logger.error(f"LLM-kerros epäonnistui: {e}")
        return []

    # Parsitaan vastaus
    try:
        content = data.get("message", {}).get("content", "")
        # Etsitään JSON vastauksen sisältä (LLM saattaa lisätä tekstiä ympärille)
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start == -1:
            return []

        parsed = json.loads(content[json_start:json_end])
        found = parsed.get("found", [])

        matches = []
        already_lower = {v.lower() for v in already_found}

        for item in found:
            value = item.get("value", "").strip()
            if not value:
                continue
            # Ohitetaan jos jo löydetty
            if value.lower() in already_lower:
                continue
            # Ohitetaan liian lyhyet (alle 2 merkkiä)
            if len(value) < 2:
                continue

            pii_type_map = {
                "PERSON": "PERSON",
                "ORGANIZATION": "ORGANIZATION",
                "ADDRESS": "ADDRESS",
                "DATE": "DATE_TIME",
                "FINANCIAL": "CUSTOM",
                "OTHER": "CUSTOM",
            }

            matches.append(LLMMatch(
                value=value,
                pii_type=pii_type_map.get(item.get("type", "OTHER"), "CUSTOM"),
                confidence=0.7,   # LLM-löydöt merkitään epävarmoiksi
                reasoning=item.get("reasoning", ""),
            ))

        logger.info(f"LLM-kerros löysi {len(matches)} uutta PII-arvoa")
        return matches

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"LLM-vastauksen parsinta epäonnistui: {e}. Vastaus: {content[:200]}")
        return []
