"""Tiny forward-only migration runner.

Migrations are SQL files in `migrations/` named `NNN_description.sql`. Each is
applied once, in numeric order, inside a transaction, and recorded in
`schema_migrations`. To change the schema later, add `002_....sql`; never edit
an applied file.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def _discover() -> list[tuple[int, str, Path]]:
    found = []
    for file in MIGRATIONS_DIR.iterdir():
        match = _NAME_RE.match(file.name)
        if match:
            found.append((int(match.group(1)), file.stem, file))
    return sorted(found)


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration not yet recorded. Returns the names applied."""
    done = applied_versions(conn)
    applied: list[str] = []
    for version, name, file in _discover():
        if version in done:
            continue
        sql = file.read_text(encoding="utf-8")
        with conn:  # transaction: all-or-nothing per migration
            conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        applied.append(name)
    return applied
