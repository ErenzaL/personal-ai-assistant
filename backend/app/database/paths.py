"""Where the database file lives.

Local-first: the file sits in the user's per-application data folder, never in
the source tree. `DATABASE_PATH` in the environment / `.env` overrides it
(handy in development, e.g. `DATABASE_PATH=./data/dev.db`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PersonalAIAssistant"
DB_FILE_NAME = "assistant.db"


def app_data_dir() -> Path:
    """Per-OS application data directory for this app."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / APP_DIR_NAME


def default_database_path() -> Path:
    return app_data_dir() / DB_FILE_NAME
