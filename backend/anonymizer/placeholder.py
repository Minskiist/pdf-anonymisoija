"""
Placeholder-engine – systeemin ydin.

Muuntaa PII-arvot ⟦TYYPPI_0001⟧ -muotoisiksi placeholdereiksi
ja pitää kirjaa kartoituksesta de-anonymisointia varten.

Placeholder-formaatti on valittu niin, että:
  - ⟦ ja ⟧ ovat harvinaisia Unicode-merkkejä → eivät esiinny normaaleissa teksteissä
  - LLM:t (ChatGPT, Gemini, Claude) jättävät ne tyypillisesti koskemattomiksi
  - Selkeästi koneluettava rakenne
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from backend.config import settings


# PII-tyyppien suomenkieliset lyhenteet
PII_TYPE_CODES = {
    # Henkilötiedot
    "PERSON":           "HLÖ",
    "PERSON_NAME":      "HLÖ",
    "LOCATION":         "PAIK",
    "ADDRESS":          "OSOITE",
    "PHONE_NUMBER":     "PUH",
    "EMAIL_ADDRESS":    "EMAIL",
    "DATE_TIME":        "PVM",
    "AGE":              "IKÄ",
    "NRP":              "HLÖ",       # Nationality, Religious, Political

    # Suomalaiset tunnisteet
    "FI_HETU":          "HETU",      # Henkilötunnus
    "FI_YTUNNUS":       "YTUN",      # Y-tunnus
    "FI_HETU_PARTIAL":  "HETU",

    # Taloudelliset tiedot
    "IBAN_CODE":        "IBAN",
    "CREDIT_CARD":      "KORTTI",
    "CRYPTO":           "KRYPTO",

    # Organisaatio
    "ORGANIZATION":     "ORG",

    # Muut
    "US_SSN":           "HTUN",
    "IP_ADDRESS":       "IP",
    "URL":              "URL",
    "MEDICAL_LICENSE":  "LÄÄK",
    "CUSTOM":           "MUUT",
}


@dataclass
class PIIMapping:
    """Yksi PII-arvo ja sen placeholder."""
    id: int
    original_value: str
    placeholder: str
    pii_type: str
    type_code: str
    confidence: float
    is_uncertain: bool        # True = näytetään käyttäjälle tarkistettavaksi
    source: str               # "presidio" | "regex" | "llm" | "manual"
    occurrences: int = 0      # Kuinka moni kertaa esiintyy dokumentissa


@dataclass
class PlaceholderEngine:
    """
    Hallinnoi placeholder-kartoitusta yhden session sisällä.

    Käyttö:
        engine = PlaceholderEngine()
        engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        anon_text = engine.anonymize(original_text)
        original_text = engine.deanonymize(anon_text)
    """

    _mappings: dict[str, PIIMapping] = field(default_factory=dict)   # original → mapping
    _by_placeholder: dict[str, PIIMapping] = field(default_factory=dict)  # placeholder → mapping
    _counters: dict[str, int] = field(default_factory=dict)           # tyyppikoodi → laskuri
    _open: str = field(default_factory=lambda: settings.placeholder_open)
    _close: str = field(default_factory=lambda: settings.placeholder_close)

    def _get_type_code(self, pii_type: str) -> str:
        return PII_TYPE_CODES.get(pii_type.upper(), "MUUT")

    def _next_id(self, type_code: str) -> int:
        self._counters[type_code] = self._counters.get(type_code, 0) + 1
        return self._counters[type_code]

    def _make_placeholder(self, type_code: str, id_num: int) -> str:
        return f"{self._open}{type_code}_{id_num:04d}{self._close}"

    def add_mapping(
        self,
        original_value: str,
        pii_type: str,
        confidence: float,
        source: str,
        is_uncertain: Optional[bool] = None,
    ) -> PIIMapping:
        """
        Lisää uusi PII-arvo kartoitukseen.
        Jos sama arvo on jo kartoitettu, palauttaa olemassa olevan.
        """
        # Normalisoidaan – sama arvo ei saa kahta placeholderia
        normalized = original_value.strip()

        if normalized in self._mappings:
            return self._mappings[normalized]

        type_code = self._get_type_code(pii_type)
        id_num = self._next_id(type_code)
        placeholder = self._make_placeholder(type_code, id_num)

        if is_uncertain is None:
            is_uncertain = confidence < settings.confidence_threshold

        mapping = PIIMapping(
            id=id_num,
            original_value=normalized,
            placeholder=placeholder,
            pii_type=pii_type,
            type_code=type_code,
            confidence=confidence,
            is_uncertain=is_uncertain,
            source=source,
        )

        self._mappings[normalized] = mapping
        self._by_placeholder[placeholder] = mapping
        return mapping

    def anonymize(self, text: str) -> tuple[str, list[PIIMapping]]:
        """
        Korvaa kaikki kartoitetut arvot placeholdereilla.

        Palauttaa: (anonymisoitu teksti, lista käytetyistä kartoituksista)
        """
        result = text
        used_mappings = []

        # Järjestetään pisimmästä lyhimpään → vältytään osittaisilta korvauksista
        # Esim. "Matti Virtanen Oy" ennen "Matti Virtanen"
        sorted_mappings = sorted(
            self._mappings.values(),
            key=lambda m: len(m.original_value),
            reverse=True,
        )

        for mapping in sorted_mappings:
            # Case-insensitive haku, säilytetään konteksti
            pattern = re.compile(r'(?<![a-zA-ZäöåÄÖÅ])' + re.escape(mapping.original_value) + r'(?![a-zA-ZäöåÄÖÅ])', re.IGNORECASE)
            matches = pattern.findall(result)

            if matches:
                mapping.occurrences = len(matches)
                result = pattern.sub(mapping.placeholder, result)
                used_mappings.append(mapping)

        return result, used_mappings

    def deanonymize(self, text: str) -> tuple[str, list[str]]:
        """
        Palauttaa placeholderit alkuperäisiksi arvoiksi.

        Palauttaa: (de-anonymisoitu teksti, lista placeholdereista joita ei löydetty)
        """
        result = text
        not_found = []

        # Etsitään kaikki placeholderit tekstistä
        pattern = re.compile(
            re.escape(self._open) + r"[A-ZÄÖÅ_0-9]+" + re.escape(self._close)
        )
        found_placeholders = set(pattern.findall(result))

        for placeholder in found_placeholders:
            if placeholder in self._by_placeholder:
                mapping = self._by_placeholder[placeholder]
                result = result.replace(placeholder, mapping.original_value)
            else:
                not_found.append(placeholder)

        return result, not_found

    def remove_mapping(self, original_value: str) -> bool:
        """Käyttäjä poistaa tunnistetun arvon listalta (ei anonymisoida)."""
        normalized = original_value.strip()
        if normalized in self._mappings:
            mapping = self._mappings.pop(normalized)
            self._by_placeholder.pop(mapping.placeholder, None)
            return True
        return False

    def get_all_mappings(self) -> list[PIIMapping]:
        """Palauttaa kaikki kartoitukset UI-listaa varten."""
        return sorted(self._mappings.values(), key=lambda m: (m.type_code, m.id))

    def get_uncertain_mappings(self) -> list[PIIMapping]:
        """Palauttaa vain epävarmat tapaukset käyttäjän tarkistettavaksi."""
        return [m for m in self._mappings.values() if m.is_uncertain]

    def to_dict(self) -> dict:
        """Serialisoi talletusta varten (SQLite)."""
        return {
            "mappings": {
                k: {
                    "id": v.id,
                    "original_value": v.original_value,
                    "placeholder": v.placeholder,
                    "pii_type": v.pii_type,
                    "type_code": v.type_code,
                    "confidence": v.confidence,
                    "is_uncertain": v.is_uncertain,
                    "source": v.source,
                    "occurrences": v.occurrences,
                }
                for k, v in self._mappings.items()
            },
            "counters": self._counters,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlaceholderEngine":
        """Lataa tallennettu tila (SQLite)."""
        engine = cls()
        engine._counters = data.get("counters", {})

        for original, m in data.get("mappings", {}).items():
            mapping = PIIMapping(**m)
            engine._mappings[original] = mapping
            engine._by_placeholder[mapping.placeholder] = mapping

        return engine
