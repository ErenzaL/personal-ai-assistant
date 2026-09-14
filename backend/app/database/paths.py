"""Where the application's data lives on disk.

Everything persistent (the SQLite database with conversations, memories,
settings and notification history) is under the per-user application-data
folder, never inside the app bundle or the source tree. Override with
`DATABASE_PATH` (handy in development, e.g. `DATABASE_PATH=./data/dev.db`).
"""

from __future__ import annotations

from pathlib import Path

from app.config import APP_DIR_NAME, app_data_dir

DB_FILE_NAME = "assistant.db"

__all__ = ["APP_DIR_NAME", "DB_FILE_NAME", "app_data_dir", "default_database_path"]


def default_database_path() -> Path:
    return app_data_dir() / DB_FILE_NAME
