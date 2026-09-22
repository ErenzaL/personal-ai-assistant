"""Plain records returned by repositories. No ORM; these mirror table rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MessageRole = Literal["user", "assistant", "system"]
TaskStatus = Literal["open", "completed", "cancelled"]
TaskPriority = Literal["low", "normal", "high"]
TASK_STATUSES: tuple[str, ...] = ("open", "completed", "cancelled")
TASK_PRIORITIES: tuple[str, ...] = ("low", "normal", "high")
MemoryCategory = Literal["profile", "preference", "routine", "goal", "project", "person", "important_fact"]
MEMORY_CATEGORIES: tuple[str, ...] = ("profile", "preference", "routine", "goal", "project", "person", "important_fact")


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: str


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    content: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Task:
    """A personal to-do. Timestamps are ISO 8601 UTC; the UI and the chat
    layer convert to local time (see `services/timeutil.py`)."""

    id: str
    title: str
    description: str
    due_at: str | None
    priority: TaskPriority
    status: TaskStatus
    remind_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    """Free-text label ("School", "Work"); "" means uncategorised."""
    category: str = ""


@dataclass(frozen=True)
class TaskItem:
    """One checklist line under a task. Deliberately independent of the
    parent task's own status: completing every item never completes the
    task itself, only a separate, explicit action does."""

    id: str
    task_id: str
    text: str
    is_completed: bool
    position: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Setting:
    key: str
    value: Any
    updated_at: str


@dataclass(frozen=True)
class Notification:
    id: str
    kind: str
    title: str
    body: str
    reference_id: str | None
    sent_at: str
    acknowledged_at: str | None


@dataclass(frozen=True)
class Memory:
    """A durable fact about the user. Independent of any conversation: a
    conversation may be deleted without taking its memories with it."""

    id: str
    category: MemoryCategory
    key: str
    content: str
    source: str
    confidence: float
    is_active: bool
    created_at: str
    updated_at: str
    """0..1: how much this matters if true, distinct from `confidence` (how
    sure the extractor was that it is true). Used to rank and prune."""
    importance: float = 0.5
    """The memory's own semantic vector, or None if none could be generated
    (no embedding-capable provider, or a transient failure)."""
    embedding: list[float] | None = None
    """Which conversation this was learned from, if any. Kept for audit only;
    never required for the memory to remain valid."""
    source_conversation_id: str | None = None
