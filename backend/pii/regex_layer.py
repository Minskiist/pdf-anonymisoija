"""
Kerros 2: Suomalaiset regex-säännöt.

Tunnistaa deterministisesti suomalaiset PII-formaatit:
  - Henkilötunnus (HETU)
  - Y-tunnus
  - Suomalaiset puhelinnumerot
  - IBAN (FI-alkuiset)
  - Luottokortit
  - Sähköpostiosoitteet
  - IP-osoitteet

Nämä ovat korkean luottamustason tunnistuksia (confidence=1.0),
koska formaatti on tiukasti määritelty.
"""

import re
import phonenumbers
from dataclasses import dataclass
from typing import Generator


@dataclass
class RegexMatch:
    value: str
    pii_type: str
    confidence: float
    start: int
    end: int


# ---------------------------------------------------------------------------
# Säännöt
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str, re.Pattern, float]] = [
    # Henkilötunnus: 010203-1234 tai 010203A1234 tai 010203+1234
    (
        "hetu",
        "FI_HETU",
        re.compile(
            r"\b(\d{6}[-+A-FU-Y]\d{3}[0-9A-FHJ-NPR-Y])\b",
            re.IGNORECASE,
        ),
        1.0,
    ),

    # Y-tunnus: 1234567-8
    (
        "ytunnus",
        "FI_YTUNNUS",
        re.compile(r"\b([0-9]{7}-[0-9])\b"),
        1.0,
    ),

    # IBAN (FI): FI21 1234 5600 0077 85 (välilyönnit sallittu)
    (
        "iban_fi",
        "IBAN_CODE",
        re.compile(
            r"\bFI\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{2}\b",
            re.IGNORECASE,
        ),
        1.0,
    ),

    # Luottokortti (16 numeroa, välilyönnit tai tavuviivat sallittu)
    (
        "credit_card",
        "CREDIT_CARD",
        re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b"),
        0.85,
    ),

    # Sähköposti
    (
        "email",
        "EMAIL_ADDRESS",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        1.0,
    ),

    # IP-osoite
    (
        "ip_address",
        "IP_ADDRESS",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        1.0,
    ),
    # Virolainen rekisterinumero: 8 numeroa (esim. 12734931)
    (
        "ee_reg",
        "EE_REGNR",
        re.compile(r"\b([0-9]{8})\b"),
        0.7,
    ),
]


# ---------------------------------------------------------------------------
# Päivämääräsuodatin – estetään päivämäärien tunnistuminen puhelinnumeroiksi
# ---------------------------------------------------------------------------

_DATE_PATTERN = re.compile(
    r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$"
)

_DATE_RANGE_PATTERN = re.compile(
    r"^\d{1,2}\.\d{1,2}\.[\u2013\-]\d{1,2}\.\d{1,2}\.\d{2,4}$"
)


def _is_date(value: str) -> bool:
    """Palauttaa True jos arvo näyttää päivämäärältä tai päivämääräväliltä."""
    v = value.strip()
    return bool(_DATE_PATTERN.match(v) or _DATE_RANGE_PATTERN.match(v))


# ---------------------------------------------------------------------------
# Puhelinnumeroiden tunnistus (phonenumbers-kirjasto)
# ---------------------------------------------------------------------------

def _find_phone_numbers(text: str) -> Generator[RegexMatch, None, None]:
    """
    Käyttää google-phonenumbers -kirjastoa suomalaisten ja kansainvälisten
    puhelinnumeroiden tunnistukseen. Paljon tarkempi kuin pelkkä regex.
    Suodattaa pois päivämäärät jotka saattavat näyttää numeroilta.
    """
    try:
        for match in phonenumbers.PhoneNumberMatcher(text, "FI"):
            number = match.number

            # Suodatetaan pois päivämäärät
            if _is_date(match.raw_string):
                continue

            if phonenumbers.is_valid_number(number):
                yield RegexMatch(
                    value=match.raw_string,
                    pii_type="PHONE_NUMBER",
                    confidence=1.0,
                    start=match.start,
                    end=match.end,
                )
    except Exception:
        # Ei pysäytetä koko pipelinea numeron parsintavirheestä
        pass


# ---------------------------------------------------------------------------
# Pääfunktio
# ---------------------------------------------------------------------------

def find_pii_regex(text: str) -> list[RegexMatch]:
    """
    Ajaa kaikki regex-säännöt ja palauttaa löydetyt PII-arvot.
    Poistaa päällekkäiset osumat (pisin voittaa).
    """
    matches: list[RegexMatch] = []

    # Regex-säännöt
    for _name, pii_type, pattern, confidence in _PATTERNS:
        for m in pattern.finditer(text):
            matches.append(RegexMatch(
                value=m.group(),
                pii_type=pii_type,
                confidence=confidence,
                start=m.start(),
                end=m.end(),
            ))

    # Puhelinnumerot (päivämääräsuodatus sisällä)
    matches.extend(_find_phone_numbers(text))

    # Poistetaan päällekkäiset – pisin match voittaa
    matches = _deduplicate(matches)

    return matches


def _deduplicate(matches: list[RegexMatch]) -> list[RegexMatch]:
    """Poistaa päällekkäiset osumat säilyttäen pisimmän."""
    if not matches:
        return []

    matches.sort(key=lambda m: (m.start, -(m.end - m.start)))

    result = [matches[0]]
    for current in matches[1:]:
        last = result[-1]
        if current.start < last.end:
            continue
        result.append(current)

    return result