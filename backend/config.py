"""
Keskitetyt asetukset â€“ kaikki konfiguroitavissa tÃ¤stÃ¤ tiedostosta.
YmpÃ¤ristÃ¶muuttujat ylikirjoittavat oletusarvot.
"""

from pydantic_settings import BaseSettings
from pathlib import Path


BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # --- Sovellus ---
    app_name: str = "PDF-anonymisoija"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- Polut ---
    data_dir: Path = BASE_DIR / "data"
    sessions_dir: Path = BASE_DIR / "data" / "sessions"
    db_path: Path = BASE_DIR / "data" / "sessions" / "sessions.db"

    # --- Tietokanta ---
    # AES-salausavain â€“ VAIHDA tuotannossa! Generoi: python -c "import secrets; print(secrets.token_hex(32))"
    db_encryption_key: str = "VAIHDA_TAMA_AVAIN_ENNEN_KAYTTOA_0000000000000000"

    # --- Session TTL ---
    session_ttl_hours: int = 24          # Sessio vanhenee 24h kuluttua
    cleanup_interval_minutes: int = 60   # Vanhojen sessioiden siivousvÃ¤li

    # --- PII-tunnistus ---
    # Luottamusraja: alle tÃ¤mÃ¤n â†’ "epÃ¤varma", nÃ¤ytetÃ¤Ã¤n kÃ¤yttÃ¤jÃ¤lle
    confidence_threshold: float = 0.75
    # KÃ¤ytÃ¤ LLM-kerrosta epÃ¤selviin tapauksiin
    use_llm_layer: bool = True
    # Kielet: presidio kÃ¤yttÃ¤Ã¤ nÃ¤itÃ¤
    supported_languages: list[str] = ["fi", "en"]

    # --- Ollama / LLM ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.6:27b"
    ollama_timeout_seconds: int = 60
    # Kontekstiikkuna PII-tunnistukselle (sanamÃ¤Ã¤rÃ¤ ympÃ¤rillÃ¤)
    llm_context_window: int = 200

    # --- Placeholder-formaatti ---
    # KÃ¤ytetÃ¤Ã¤n: âŸ¦TYYPPI_0001âŸ§
    placeholder_open: str = "âŸ¦"
    placeholder_close: str = "âŸ§"

    # --- PDF ---
    max_pdf_size_mb: int = 50
    # OCR-hook: False = ei kÃ¤ytetÃ¤, True = kÃ¤ytetÃ¤Ã¤n Tesseractia (tuleva ominaisuus)
    ocr_enabled: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Singleton â€“ importataan kaikkialle tÃ¤stÃ¤
settings = Settings()

# Varmistetaan hakemistot
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.sessions_dir.mkdir(parents=True, exist_ok=True)
