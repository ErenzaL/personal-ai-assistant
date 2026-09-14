from __future__ import annotations

import sqlite3

from app.database.models import Note
from app.database.repositories._base import Repository, new_id, now


def _note(row: sqlite3.Row) -> Note:
    return Note(row["id"], row["title"], row["content"], row["created_at"], row["updated_at"])


class NoteRepository(Repository):
    def create(self, title: str = "", content: str = "") -> Note:
        ts = now()
        record = Note(new_id(), title, content, ts, ts)
        self._write(
            "INSERT INTO notes (id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (record.id, record.title, record.content, record.created_at, record.updated_at),
        )
        return record

    def get(self, note_id: str) -> Note | None:
        row = self._one("SELECT * FROM notes WHERE id = ?", (note_id,))
        return _note(row) if row else None

    def list(self, limit: int = 100) -> list[Note]:
        rows = self._all("SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [_note(r) for r in rows]

    def update(self, note_id: str, *, title: str | None = None, content: str | None = None) -> Note | None:
        """Change the given fields only; returns the updated note or None if missing."""
        current = self.get(note_id)
        if current is None:
            return None
        updated = Note(
            current.id,
            current.title if title is None else title,
            current.content if content is None else content,
            current.created_at,
            now(),
        )
        self._write(
            "UPDATE notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
            (updated.title, updated.content, updated.updated_at, note_id),
        )
        return updated

    def delete(self, note_id: str) -> bool:
        return self._write("DELETE FROM notes WHERE id = ?", (note_id,)) == 1
