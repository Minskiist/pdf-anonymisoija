"""
PDF-generaattori – luo uuden PDF:n tekstistä.

Tuottaa siistin, selkeän PDF:n de-anonymisoidusta tekstistä.
Layout ei vastaa alkuperäistä (tämä on tietoinen päätös –
LLM on saattanut muokata sisältöä).

Alkuperäinen PDF säilytetään muuttumattomana arkistona.
"""

from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


def generate_pdf(text: str, title: str = "Dokumentti") -> bytes:
    """
    Luo PDF-tiedoston tekstistä.

    Args:
        text: Teksti josta PDF luodaan (de-anonymisoitu)
        title: Dokumentin otsikko

    Returns:
        PDF-tiedoston sisältö tavuina
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.enums import TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

    except ImportError:
        raise RuntimeError(
            "ReportLab ei ole asennettu. Asenna: pip install reportlab"
        )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title=title,
    )

    styles = getSampleStyleSheet()

    # Otsikkotyyli
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=16,
        spaceAfter=20,
    )

    # Leipätekstiä varten – rivinvaihto-turvallinen
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=16,
        spaceAfter=8,
        alignment=TA_LEFT,
    )

    # Sivuerotintyyli
    page_header_style = ParagraphStyle(
        "PageHeader",
        parent=styles["Heading2"],
        fontSize=11,
        textColor="#555555",
        spaceBefore=16,
        spaceAfter=8,
    )

    story = []

    # Lisätään otsikko
    story.append(Paragraph(_escape_xml(title), title_style))
    story.append(Spacer(1, 0.3 * cm))

    # Parsitaan sivut [Sivu N] -erottimien perusteella
    sections = _split_into_sections(text)

    for section_title, section_text in sections:
        if section_title:
            story.append(Paragraph(_escape_xml(section_title), page_header_style))

        # Jaetaan kappaleet tyhjien rivien perusteella
        paragraphs = section_text.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # Muutetaan yksittäiset rivinvaihdot <br/>-tageiksi
            para_html = para.replace("\n", "<br/>")
            story.append(Paragraph(_escape_xml_keep_br(para_html), body_style))
            story.append(Spacer(1, 0.1 * cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def _escape_xml(text: str) -> str:
    """Escapetaan XML-erikoismerkit ReportLab-tekstiä varten."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
        # Suojataan myös placeholder-merkit
        .replace("⟦", "[")
        .replace("⟧", "]")
    )


def _escape_xml_keep_br(text: str) -> str:
    """Kuten _escape_xml mutta säilyttää <br/> -tagit."""
    # Korvataan <br/> ennen escapea
    placeholder_br = "__BR_PLACEHOLDER__"
    text = text.replace("<br/>", placeholder_br)
    text = _escape_xml(text)
    return text.replace(placeholder_br, "<br/>")


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """
    Jakaa tekstin osioihin [Sivu N] -erottimien perusteella.

    Returns:
        Lista (otsikko, teksti) -pareista
    """
    import re

    pattern = re.compile(r"\[Sivu \d+\]", re.MULTILINE)
    parts = pattern.split(text)
    headers = [""] + pattern.findall(text)  # Ensimmäisellä ei ole otsikkoa

    sections = []
    for header, content in zip(headers, parts):
        if content.strip():
            sections.append((header, content.strip()))

    return sections if sections else [("", text)]
