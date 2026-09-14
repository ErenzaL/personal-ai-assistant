from __future__ import annotations

import json
from typing import Any

from app.database.models import Setting
from app.database.repositories._base import Repository, now


class SettingsRepository(Repository):
    """Key/value store. Values are JSON-encoded, so str, int, bool, list and
    dict all round-trip unchanged."""

    def get(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def get_record(self, key: str) -> Setting | None:
        row = self._one("SELECT * FROM settings WHERE key = ?", (key,))
        return Setting(row["key"], json.loads(row["value"]), row["updated_at"]) if row else None

    def set(self, key: str, value: Any) -> None:
        self._write(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), now()),
        )

    def delete(self, key: str) -> bool:
        return self._write("DELETE FROM settings WHERE key = ?", (key,)) == 1

    def all(self) -> dict[str, Any]:
        return {row["key"]: json.loads(row["value"]) for row in self._all("SELECT key, value FROM settings")}
