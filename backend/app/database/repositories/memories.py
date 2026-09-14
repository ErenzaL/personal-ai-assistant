from __future__ import annotations

import sqlite3

from app.database.models import Memory, MemoryCategory
from app.database.repositories._base import Repository, new_id, now
from app.services.embeddings import decode as decode_embedding
from app.services.embeddings import encode as encode_embedding


def _memory(row: sqlite3.Row) -> Memory:
    keys = row.keys()
    return Memory(
        row["id"],
        row["category"],
        row["key"],
        row["content"],
        row["source"],
        float(row["confidence"]),
        bool(row["is_active"]),
        row["created_at"],
        row["updated_at"],
        importance=float(row["importance"]) if "importance" in keys else 0.5,
        embedding=decode_embedding(row["embedding"]) if "embedding" in keys else None,
        source_conversation_id=row["source_conversation_id"] if "source_conversation_id" in keys else None,
    )


def _like_pattern(text: str) -> str:
    """Escape LIKE wildcards in user input and wrap for substring matching."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class _Unset:
    """Distinct from None, so `update(embedding=None)` can mean "clear it"
    while an omitted argument means "leave as is"."""


_UNSET = _Unset()


class MemoryRepository(Repository):
    """Durable facts about the user. Independent of conversations/messages."""

    def list_with_embeddings(self, *, active_only: bool = True) -> list[Memory]:
        """Every memory that has a vector to compare against, for semantic
        retrieval. A plain Python scan is fine at personal-use scale (dozens
        to a few hundred rows); no vector index is needed for V1."""
        where = " WHERE is_active = 1 AND embedding IS NOT NULL" if active_only else " WHERE embedding IS NOT NULL"
        rows = self._all(f"SELECT * FROM memories{where}", ())
        return [_memory(r) for r in rows]

    def create(
        self,
        category: MemoryCategory,
        key: str,
        content: str,
        *,
        source: str = "user",
        confidence: float = 1.0,
        importance: float = 0.5,
        embedding: list[float] | None = None,
        source_conversation_id: str | None = None,
    ) -> Memory:
        """Insert. Raises sqlite3.IntegrityError if (category, key) already exists."""
        ts = now()
        record = Memory(
            new_id(), category, key, content, source, confidence, True, ts, ts,
            importance=importance, embedding=embedding, source_conversation_id=source_conversation_id,
        )
        self._write(
            """
            INSERT INTO memories (
                id, category, key, content, source, confidence, is_active, created_at, updated_at,
                importance, embedding, source_conversation_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                record.id, category, key, content, source, confidence, ts, ts,
                importance, encode_embedding(embedding) if embedding is not None else None,
                source_conversation_id,
            ),
        )
        return record

    def get(self, memory_id: str) -> Memory | None:
        row = self._one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return _memory(row) if row else None

    def get_by_key(self, category: MemoryCategory, key: str) -> Memory | None:
        row = self._one("SELECT * FROM memories WHERE category = ? AND key = ?", (category, key))
        return _memory(row) if row else None

    def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        source: str | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        embedding: list[float] | None | _Unset = _UNSET,
        source_conversation_id: str | None = None,
    ) -> Memory | None:
        """Change the given fields only; returns the updated record or None if
        missing. `embedding` distinguishes "leave as is" (omitted) from
        "clear it" (explicit None), since a memory legitimately has no
        embedding sometimes; every other field uses None for "leave as is"."""
        current = self.get(memory_id)
        if current is None:
            return None
        new_embedding = current.embedding if embedding is _UNSET else embedding
        updated = Memory(
            current.id,
            current.category,
            current.key,
            current.content if content is None else content,
            current.source if source is None else source,
            current.confidence if confidence is None else confidence,
            current.is_active,
            current.created_at,
            now(),
            importance=current.importance if importance is None else importance,
            embedding=new_embedding,
            source_conversation_id=current.source_conversation_id
            if source_conversation_id is None
            else source_conversation_id,
        )
        self._write(
            """UPDATE memories SET content = ?, source = ?, confidence = ?, updated_at = ?,
               importance = ?, embedding = ?, source_conversation_id = ? WHERE id = ?""",
            (
                updated.content, updated.source, updated.confidence, updated.updated_at,
                updated.importance, encode_embedding(new_embedding) if new_embedding is not None else None,
                updated.source_conversation_id, memory_id,
            ),
        )
        return updated

    def set_active(self, memory_id: str, active: bool) -> Memory | None:
        changed = self._write(
            "UPDATE memories SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if active else 0, now(), memory_id),
        )
        return self.get(memory_id) if changed else None

    def list(
        self,
        *,
        category: MemoryCategory | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[Memory]:
        where, params = self._filters(category=category, active_only=active_only)
        rows = self._all(
            f"SELECT * FROM memories{where} ORDER BY category, key LIMIT ?",
            (*params, limit),
        )
        return [_memory(r) for r in rows]

    def search(
        self,
        query: str | None = None,
        *,
        category: MemoryCategory | None = None,
        key: str | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[Memory]:
        """Filter by category and/or exact key, plus case-insensitive substring
        match of `query` against key and content."""
        where, params = self._filters(category=category, active_only=active_only)
        clauses = [where[len(" WHERE ") :]] if where else []
        if key:
            clauses.append("key = ?")
            params.append(key)
        if query and query.strip():
            pattern = _like_pattern(query.strip())
            clauses.append("(content LIKE ? ESCAPE '\\' OR key LIKE ? ESCAPE '\\')")
            params.extend([pattern, pattern])
        sql = "SELECT * FROM memories"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        rows = self._all(sql, (*params, limit))
        return [_memory(r) for r in rows]

    @staticmethod
    def _filters(*, category: MemoryCategory | None, active_only: bool) -> tuple[str, list]:
        clauses, params = [], []
        if active_only:
            clauses.append("is_active = 1")
        if category:
            clauses.append("category = ?")
            params.append(category)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params
