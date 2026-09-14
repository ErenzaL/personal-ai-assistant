"""Helpers shared by repositories."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    """Current time as ISO 8601 UTC with second precision, e.g. 2026-09-14T09:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def _write(self, sql: str, params: tuple = ()) -> int:
        """Execute a statement, commit, and return the number of affected rows."""
        with self.conn:
            cursor = self.conn.execute(sql, params)
            return cursor.rowcount
