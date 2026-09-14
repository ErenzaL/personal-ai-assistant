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
    """A durable fact about the user. Not tied to any conversation."""

    id: str
    category: MemoryCategory
    key: str
    content: str
    source: str
    confidence: float
    is_active: bool
    created_at: str
    updated_at: str
