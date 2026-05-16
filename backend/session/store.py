"""
Session store – salattu SQLite-tietokanta sessioille.

Jokainen sessio sisältää:
  - Istunnon UUID
  - PlaceholderEnginen tilan (JSON, salattu)
  - Alkuperäisen PDF:n nimen
  - Luonti- ja vanhentumisaikaleiman

Salaus: Fernet (AES-128-CBC + HMAC-SHA256) – symmetrinen, nopea.
Avain konfiguroidaan settings.db_encryption_key:ssä.

TÄRKEÄÄ: Vaihda avain ennen tuotantokäyttöä!
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib

from backend.config import settings
from backend.anonymizer.placeholder import PlaceholderEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Salausapurit
# ---------------------------------------------------------------------------

def _make_fernet() -> Fernet:
    """Luo Fernet-objekti settings-avaimesta."""
    # Muunnetaan merkkijono avain 32 tavun Fernet-avaimeksi
    key_bytes = settings.db_encryption_key.encode()
    # SHA-256 hash → 32 tavua → base64url
    hashed = hashlib.sha256(key_bytes).digest()
    fernet_key = base64.urlsafe_b64encode(hashed)
    return Fernet(fernet_key)


def _encrypt(data: str) -> str:
    """Salaa merkkijono, palauttaa base64-merkkijonon."""
    f = _make_fernet()
    return f.encrypt(data.encode()).decode()


def _decrypt(data: str) -> str:
    """Purkaa salatun merkkijonon."""
    f = _make_fernet()
    try:
        return f.decrypt(data.encode()).decode()
    except InvalidToken as e:
        raise ValueError(f"Salauksen purku epäonnistui – väärä avain tai vioittunut data: {e}")


# ---------------------------------------------------------------------------
# Tietokantarakenne
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    engine_data  TEXT NOT NULL,     -- Salattu JSON
    language     TEXT DEFAULT 'fi',
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);
"""


def _get_connection() -> sqlite3.Connection:
    """Avaa tietokantayhteyden. Luo tiedoston ja taulut tarvittaessa."""
    db_path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Julkiset funktiot
# ---------------------------------------------------------------------------

def create_session(
    engine: PlaceholderEngine,
    filename: str,
    language: str = "fi",
) -> str:
    """
    Luo uusi sessio ja tallentaa sen tietokantaan.

    Returns:
        Sessio-UUID (merkkijono)
    """
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.session_ttl_hours)

    engine_json = json.dumps(engine.to_dict(), ensure_ascii=False)
    encrypted = _encrypt(engine_json)

    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO sessions (session_id, filename, engine_data, language, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                filename,
                encrypted,
                language,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )

    logger.info(f"Sessio luotu: {session_id} (vanhenee {expires_at.isoformat()})")
    return session_id


def load_session(session_id: str) -> tuple[PlaceholderEngine, str, str] | None:
    """
    Lataa sessio tietokannasta.

    Returns:
        (PlaceholderEngine, filename, language) tai None jos ei löydy / vanhentunut
    """
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    if row is None:
        logger.warning(f"Sessiota ei löydy: {session_id}")
        return None

    # Tarkistetaan vanhentuminen
    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        logger.info(f"Sessio vanhentunut: {session_id}")
        delete_session(session_id)
        return None

    try:
        engine_json = _decrypt(row["engine_data"])
        engine_data = json.loads(engine_json)
        engine = PlaceholderEngine.from_dict(engine_data)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"Session {session_id} lataus epäonnistui: {e}")
        return None

    return engine, row["filename"], row["language"]


def update_session(session_id: str, engine: PlaceholderEngine) -> bool:
    """Päivittää session PlaceholderEnginen (esim. käyttäjä lisää PII:tä)."""
    engine_json = json.dumps(engine.to_dict(), ensure_ascii=False)
    encrypted = _encrypt(engine_json)

    with _get_connection() as conn:
        result = conn.execute(
            "UPDATE sessions SET engine_data = ? WHERE session_id = ?",
            (encrypted, session_id),
        )

    if result.rowcount == 0:
        logger.warning(f"Päivitys epäonnistui – sessiota ei löydy: {session_id}")
        return False

    return True


def delete_session(session_id: str) -> bool:
    """Poistaa session välittömästi (käyttäjän pyyntö tai TTL)."""
    with _get_connection() as conn:
        result = conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )

    deleted = result.rowcount > 0
    if deleted:
        logger.info(f"Sessio poistettu: {session_id}")
    return deleted


def delete_all_sessions() -> int:
    """Poistaa KAIKKI sessiot (käyttäjän 'tyhjennä kaikki' -toiminto)."""
    with _get_connection() as conn:
        result = conn.execute("DELETE FROM sessions")
    count = result.rowcount
    logger.info(f"Kaikki sessiot poistettu: {count} kpl")
    return count


def cleanup_expired_sessions() -> int:
    """Poistaa vanhentuneet sessiot. Ajetaan ajastimella."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        result = conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?",
            (now,),
        )
    count = result.rowcount
    if count > 0:
        logger.info(f"Vanhentuneita sessioita poistettu: {count} kpl")
    return count


def list_sessions() -> list[dict]:
    """Listaa aktiiviset sessiot (UI:ta varten)."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT session_id, filename, language, created_at, expires_at "
            "FROM sessions WHERE expires_at > ? ORDER BY created_at DESC",
            (now,),
        ).fetchall()

    return [
        {
            "session_id": row["session_id"],
            "filename": row["filename"],
            "language": row["language"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
        for row in rows
    ]
