"""Long-term personal memory.

Durable facts about the user (preferences, routines, projects, people...),
stored on purpose and independent of any conversation. Nothing here is
called automatically from chat: memories are created only through the
memory API (and, later, through explicit "remember this" flows with
confirmation). Retrieval into the prompt is a later step.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.database.models import MEMORY_CATEGORIES, Memory, MemoryCategory
from app.database.repositories.memories import MemoryRepository

KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
KEY_STOPWORDS = {
    "the", "a", "an", "my", "me", "i", "is", "are", "to", "of", "and", "or", "in", "on", "for",
    "with", "that", "this", "it", "user", "prefers", "prefer", "likes", "like", "wants", "want",
}
KEY_MAX_LEN = 64
CONTENT_MAX_LEN = 1000
# "auto": saved by the passive extraction pipeline, without the user
# explicitly asking. "user"/"assistant"/"import" are the older, still-valid
# provenances (a memory created before this feature, or by whatever the
# manual API endpoint still allows).
SOURCES = ("user", "assistant", "import", "auto")


class MemoryError(Exception):
    """Base class; `message` is safe to show."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidMemory(MemoryError):
    pass


class MemoryNotFound(MemoryError):
    pass


class MemoryConflict(MemoryError):
    pass


# Sentinel distinct from None: an omitted `embedding` argument means "leave
# it as is," while an explicit None means "clear it."
_NO_CHANGE = object()


class MemoryService:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._repo = MemoryRepository(db)

    def list_with_embeddings(self) -> list[Memory]:
        """Active memories that have a vector to compare against."""
        return self._repo.list_with_embeddings()

    # --- writes ---

    def create_memory(
        self,
        category: str,
        key: str | None,
        content: str,
        *,
        source: str = "user",
        confidence: float = 1.0,
        importance: float = 0.5,
        embedding: list[float] | None = None,
        source_conversation_id: str | None = None,
    ) -> Memory:
        """Create a memory. `key` may be None, in which case one is derived
        from the content (and suffixed if that slug is taken), so callers that
        have no meaningful key -- such as the settings UI -- never invent one."""
        category = _valid_category(category)
        content = _valid_content(content)
        source = _valid_source(source)
        confidence = _valid_confidence(confidence)
        importance = _valid_importance(importance)
        if key is None:
            key = self._free_key(category, slug_key(content))
        else:
            key = _valid_key(key)
            existing = self._repo.get_by_key(category, key)
            if existing is not None:
                state = "active" if existing.is_active else "inactive"
                raise MemoryConflict(
                    f"A {category} memory with key '{key}' already exists ({state}, id {existing.id}). "
                    "Update it instead."
                )
        return self._repo.create(
            category, key, content, source=source, confidence=confidence,
            importance=importance, embedding=embedding, source_conversation_id=source_conversation_id,
        )

    def _free_key(self, category: MemoryCategory, base: str) -> str:
        """First unused key of the form base, base_2, base_3, ..."""
        if self._repo.get_by_key(category, base) is None:
            return base
        for n in range(2, 100):
            candidate = f"{base[: KEY_MAX_LEN - 4]}_{n}"
            if self._repo.get_by_key(category, candidate) is None:
                return candidate
        raise MemoryConflict("Too many similar memories; give this one a clearer wording.")

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        source: str | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        embedding: list[float] | None | object = _NO_CHANGE,
        source_conversation_id: str | None = None,
    ) -> Memory:
        if content is None and source is None and confidence is None and importance is None and embedding is _NO_CHANGE:
            raise InvalidMemory("Nothing to update.")
        repo_kwargs: dict[str, Any] = {}
        # The repository has its own "leave as is" sentinel; only pass
        # `embedding` through when this call actually specifies one
        # (including an explicit None, which means "clear it").
        if embedding is not _NO_CHANGE:
            repo_kwargs["embedding"] = embedding
        updated = self._repo.update(
            memory_id,
            content=_valid_content(content) if content is not None else None,
            source=_valid_source(source) if source is not None else None,
            confidence=_valid_confidence(confidence) if confidence is not None else None,
            importance=_valid_importance(importance) if importance is not None else None,
            source_conversation_id=source_conversation_id,
            **repo_kwargs,
        )
        if updated is None:
            raise MemoryNotFound(f"No memory with id {memory_id}.")
        return updated

    def deactivate_all(self, *, category: str | None = None) -> int:
        """Deactivate every active memory (optionally in one category).
        Returns how many were changed. Rows are kept, as always."""
        cat = _valid_category(category) if category else None
        items = self._repo.list(category=cat, active_only=True)
        for record in items:
            self._repo.set_active(record.id, False)
        return len(items)

    def deactivate_memory(self, memory_id: str) -> Memory:
        """Preferred over deletion: the row stays for audit, but is excluded
        from lists, searches, and (later) prompt retrieval."""
        record = self._repo.set_active(memory_id, False)
        if record is None:
            raise MemoryNotFound(f"No memory with id {memory_id}.")
        return record

    def reactivate_memory(self, memory_id: str) -> Memory:
        record = self._repo.set_active(memory_id, True)
        if record is None:
            raise MemoryNotFound(f"No memory with id {memory_id}.")
        return record

    # --- reads ---

    def get_memory(self, memory_id: str) -> Memory:
        record = self._repo.get(memory_id)
        if record is None:
            raise MemoryNotFound(f"No memory with id {memory_id}.")
        return record

    def list_memories(self, *, category: str | None = None, include_inactive: bool = False) -> list[Memory]:
        cat = _valid_category(category) if category else None
        return self._repo.list(category=cat, active_only=not include_inactive)

    def search_memories(
        self,
        query: str | None = None,
        *,
        category: str | None = None,
        key: str | None = None,
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[Memory]:
        cat = _valid_category(category) if category else None
        return self._repo.search(query, category=cat, key=key, active_only=not include_inactive, limit=limit)


def slug_key(content: str) -> str:
    """A stable lower_snake_case key derived from a memory's wording."""
    words = [w for w in re.findall(r"[a-z0-9]+", content.lower()) if w not in KEY_STOPWORDS][:4]
    return ("_".join(words) or "fact")[:KEY_MAX_LEN]


# --- validation ---


def _valid_category(category: str) -> MemoryCategory:
    value = category.strip().lower()
    if value not in MEMORY_CATEGORIES:
        raise InvalidMemory(f"Unknown category '{category}'. Allowed: {', '.join(MEMORY_CATEGORIES)}.")
    return value  # type: ignore[return-value]


def _valid_key(key: str) -> str:
    value = key.strip().lower()
    if not value or len(value) > KEY_MAX_LEN or not KEY_PATTERN.match(value):
        raise InvalidMemory("Key must be lowercase letters, digits and underscores, e.g. preferred_meeting_time.")
    return value


def _valid_content(content: str) -> str:
    value = content.strip()
    if not value:
        raise InvalidMemory("Content must not be empty.")
    if len(value) > CONTENT_MAX_LEN:
        raise InvalidMemory(f"Content must be at most {CONTENT_MAX_LEN} characters.")
    return value


def _valid_source(source: str) -> str:
    value = source.strip().lower()
    if value not in SOURCES:
        raise InvalidMemory(f"Source must be one of: {', '.join(SOURCES)}.")
    return value


def _valid_confidence(confidence: float) -> float:
    if not 0.0 <= confidence <= 1.0:
        raise InvalidMemory("Confidence must be between 0 and 1.")
    return float(confidence)


def _valid_importance(importance: float) -> float:
    if not 0.0 <= importance <= 1.0:
        raise InvalidMemory("Importance must be between 0 and 1.")
    return float(importance)
