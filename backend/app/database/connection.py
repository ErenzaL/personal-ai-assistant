"""Connections and one-time initialisation."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from app.config import get_settings
from app.database.migrations import apply_migrations

log = logging.getLogger("app.database")


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with the settings every caller should have.

    - rows come back as `sqlite3.Row` (dict-like access by column name)
    - foreign keys are enforced (off by default in SQLite)
    - `busy_timeout` waits briefly instead of failing if another connection
      holds a write lock (the reload server and a request can overlap)
    """
    # check_same_thread=False: FastAPI runs the sync `get_db` dependency in a
    # worker thread but async routes use the connection on the event-loop
    # thread. A connection is still only ever used by one thread at a time.
    conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_database(path: Path) -> None:
    """Create the file, its folder, and the schema if missing; apply any
    pending migrations. Safe to call on every startup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        # WAL: readers don't block the writer; persists in the file.
        conn.execute("PRAGMA journal_mode = WAL")
        applied = apply_migrations(conn)
        if applied:
            log.info("database: applied migrations %s", ", ".join(applied))
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed.

    Usage: `def route(db: sqlite3.Connection = Depends(get_db)):`
    Routes using it should be plain `def` (FastAPI runs them in a thread pool),
    since sqlite3 is synchronous.
    """
    conn = connect(get_settings().database_path)
    try:
        yield conn
    finally:
        conn.close()
