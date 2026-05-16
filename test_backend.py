"""
Yksikkötestit backend-ytimelle.

Testit voidaan ajaa ilman LLM:ää tai Ollamaa:
  pytest tests/ -v

LLM-testit ohitetaan automaattisesti jos Ollama ei ole käynnissä.
"""

import json
import pytest
import asyncio
from pathlib import Path


# ---------------------------------------------------------------------------
# PlaceholderEngine-testit
# ---------------------------------------------------------------------------

class TestPlaceholderEngine:

    def setup_method(self):
        from backend.anonymizer.placeholder import PlaceholderEngine
        self.engine = PlaceholderEngine()

    def test_lisaa_kartoitus(self):
        mapping = self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        assert mapping.placeholder == "⟦HLÖ_0001⟧"
        assert mapping.original_value == "Matti Virtanen"
        assert mapping.type_code == "HLÖ"

    def test_sama_arvo_ei_duplikaattia(self):
        m1 = self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        m2 = self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        assert m1.placeholder == m2.placeholder

    def test_eri_tyypit_eri_laskurit(self):
        m1 = self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "regex")
        m2 = self.engine.add_mapping("FI21 1234 5600 0077 85", "IBAN_CODE", 1.0, "regex")
        m3 = self.engine.add_mapping("Liisa Korhonen", "PERSON", 0.90, "presidio")

        assert m1.type_code == "HLÖ"
        assert m2.type_code == "IBAN"
        assert m3.type_code == "HLÖ"
        assert m1.placeholder == "⟦HLÖ_0001⟧"
        assert m3.placeholder == "⟦HLÖ_0002⟧"

    def test_anonymisointi(self):
        self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        self.engine.add_mapping("040-123 4567", "PHONE_NUMBER", 1.0, "regex")

        teksti = "Sopimuksen osapuoli on Matti Virtanen, puh. 040-123 4567."
        anon, used = self.engine.anonymize(teksti)

        assert "Matti Virtanen" not in anon
        assert "040-123 4567" not in anon
        assert "⟦HLÖ_0001⟧" in anon
        assert "⟦PUH_0001⟧" in anon
        assert len(used) == 2

    def test_deanonymisointi(self):
        self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        teksti = "Sopimus: Matti Virtanen"
        anon, _ = self.engine.anonymize(teksti)
        deanon, not_found = self.engine.deanonymize(anon)

        assert "Matti Virtanen" in deanon
        assert len(not_found) == 0

    def test_tuntematon_placeholder(self):
        teksti = "Vastaus sisältää ⟦HLÖ_9999⟧ tunnistamattoman placeholderin."
        deanon, not_found = self.engine.deanonymize(teksti)

        assert "⟦HLÖ_9999⟧" in not_found

    def test_serialisointi(self):
        self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        data = self.engine.to_dict()

        from backend.anonymizer.placeholder import PlaceholderEngine
        restored = PlaceholderEngine.from_dict(data)

        assert len(restored.get_all_mappings()) == 1
        assert restored.get_all_mappings()[0].original_value == "Matti Virtanen"

    def test_poisto(self):
        self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        assert len(self.engine.get_all_mappings()) == 1

        self.engine.remove_mapping("Matti Virtanen")
        assert len(self.engine.get_all_mappings()) == 0

    def test_epävarma_luottamus(self):
        m = self.engine.add_mapping("Nordea", "ORGANIZATION", 0.6, "presidio")
        assert m.is_uncertain is True

    def test_varma_luottamus(self):
        m = self.engine.add_mapping("FI21 1234 5600 0077 85", "IBAN_CODE", 1.0, "regex")
        assert m.is_uncertain is False

    def test_anonymisointi_case_insensitive(self):
        self.engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")
        teksti = "MATTI VIRTANEN allekirjoitti sopimuksen."
        anon, used = self.engine.anonymize(teksti)
        assert "MATTI VIRTANEN" not in anon
        assert len(used) == 1


# ---------------------------------------------------------------------------
# Regex-kerros-testit
# ---------------------------------------------------------------------------

class TestRegexLayer:

    def test_hetu_tunnistus(self):
        from backend.pii.regex_layer import find_pii_regex

        teksti = "Henkilötunnus: 010203-1234 on annettu."
        matches = find_pii_regex(teksti)

        assert any(m.pii_type == "FI_HETU" and "010203-1234" in m.value for m in matches)

    def test_ytunnus_tunnistus(self):
        from backend.pii.regex_layer import find_pii_regex

        teksti = "Y-tunnus: 1234567-8"
        matches = find_pii_regex(teksti)

        assert any(m.pii_type == "FI_YTUNNUS" for m in matches)

    def test_iban_tunnistus(self):
        from backend.pii.regex_layer import find_pii_regex

        teksti = "Tilinumero: FI21 1234 5600 0077 85"
        matches = find_pii_regex(teksti)

        assert any(m.pii_type == "IBAN_CODE" for m in matches)

    def test_email_tunnistus(self):
        from backend.pii.regex_layer import find_pii_regex

        teksti = "Sähköposti: matti.virtanen@esimerkki.fi"
        matches = find_pii_regex(teksti)

        assert any(m.pii_type == "EMAIL_ADDRESS" for m in matches)

    def test_ei_vaaraa_positiivista(self):
        from backend.pii.regex_layer import find_pii_regex

        teksti = "Tämä on normaali teksti ilman henkilötietoja."
        matches = find_pii_regex(teksti)

        assert len(matches) == 0


# ---------------------------------------------------------------------------
# Session store -testit
# ---------------------------------------------------------------------------

class TestSessionStore:

    def setup_method(self):
        """Käytetään testitietokantaa."""
        import tempfile
        from backend.config import settings
        self._tmpdir = tempfile.mkdtemp()
        settings.db_path = Path(self._tmpdir) / "test_sessions.db"

    def test_sessio_luonti_ja_lataus(self):
        from backend.anonymizer.placeholder import PlaceholderEngine
        from backend.session import store

        engine = PlaceholderEngine()
        engine.add_mapping("Matti Virtanen", "PERSON", 0.95, "presidio")

        session_id = store.create_session(engine, "testi.pdf", "fi")
        assert session_id is not None

        result = store.load_session(session_id)
        assert result is not None

        loaded_engine, filename, language = result
        assert filename == "testi.pdf"
        assert language == "fi"
        assert len(loaded_engine.get_all_mappings()) == 1

    def test_sessio_poisto(self):
        from backend.anonymizer.placeholder import PlaceholderEngine
        from backend.session import store

        engine = PlaceholderEngine()
        session_id = store.create_session(engine, "testi.pdf")

        store.delete_session(session_id)
        result = store.load_session(session_id)
        assert result is None

    def test_sessio_paivitys(self):
        from backend.anonymizer.placeholder import PlaceholderEngine
        from backend.session import store

        engine = PlaceholderEngine()
        session_id = store.create_session(engine, "testi.pdf")

        engine.add_mapping("Lisätty myöhemmin", "PERSON", 0.9, "manual")
        store.update_session(session_id, engine)

        result = store.load_session(session_id)
        assert result is not None
        loaded_engine, _, _ = result
        assert len(loaded_engine.get_all_mappings()) == 1


# ---------------------------------------------------------------------------
# Integraatiotesti (ilman LLM:ää)
# ---------------------------------------------------------------------------

class TestIntegration:

    @pytest.mark.asyncio
    async def test_koko_pipeline_ilman_llm(self):
        """Testaa koko pipeline: teksti → PII-analyysi → anonymisointi → de-anonymisointi."""
        from backend.config import settings
        settings.use_llm_layer = False   # Ohitetaan LLM tässä testissä

        from backend.pii.engine import analyze_text

        teksti = """
        Sopimus nro 2024-001

        Sopimusosapuolet:
        Toimittaja: Matti Virtanen (HETU: 010203-1234)
        Sähköposti: matti.virtanen@esimerkki.fi
        Puhelin: +358 40 123 4567

        Tilinumero: FI21 1234 5600 0077 85

        Sopimuksen arvo: 50 000 euroa.
        """

        result = await analyze_text(teksti)
        assert result.total_found > 0

        # Anonymisointi
        anon_text, used = result.engine.anonymize(teksti)
        assert "Matti Virtanen" not in anon_text
        assert "010203-1234" not in anon_text
        assert "FI21 1234 5600 0077 85" not in anon_text

        # De-anonymisointi
        deanon_text, not_found = result.engine.deanonymize(anon_text)
        assert "Matti Virtanen" in deanon_text
        assert len(not_found) == 0
