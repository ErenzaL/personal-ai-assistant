"""Settings loaded from the environment and a `.env` file.

Secrets live here and nowhere else. Nothing in this module is ever returned by
an HTTP endpoint or logged.

Where the file lives: `backend/.env` in development; the packaged backend
(one executable, no source folder) reads `.env` from the app-data folder
instead, which is also where the database is. Real environment variables take
precedence over either file.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
# True inside the PyInstaller-built executable.
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR_NAME = "PersonalAIAssistant"


def app_data_dir() -> Path:
    """Per-user application-data folder: the database, the key file, logs."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / APP_DIR_NAME


def _load_env_files() -> None:
    # `load_dotenv` never overrides a variable that is already set, so the
    # first file wins and real environment variables win over both.
    if not FROZEN:
        load_dotenv(BACKEND_DIR / ".env")
    load_dotenv(app_data_dir() / ".env")


_load_env_files()


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    gemini_api_key: str | None
    gemini_model: str
    groq_api_key: str | None
    groq_model: str
    llm_timeout_seconds: float
    database_path: Path


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _database_path() -> Path:
    """`DATABASE_PATH` if set (relative paths resolve against backend/),
    otherwise the per-OS application-data folder."""
    # Imported here, not at module level: the database package imports this
    # module for `get_db`, so a top-level import would be circular.
    from app.database.paths import default_database_path

    override = _optional("DATABASE_PATH")
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()
    return default_database_path()


@lru_cache
def get_settings() -> Settings:
    return Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "gemini").strip().lower(),
        gemini_api_key=_optional("GEMINI_API_KEY"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
        groq_api_key=_optional("GROQ_API_KEY"),
        groq_model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "30")),
        database_path=_database_path(),
    )
