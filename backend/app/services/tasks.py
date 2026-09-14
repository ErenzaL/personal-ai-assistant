"""Personal task management.

Deterministic: every state change goes through here, never through the model.
Timestamps arrive as local-time ISO strings (what a person or the interpreter
produces) and are stored as UTC.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from app.database.models import TASK_PRIORITIES, TASK_STATUSES, Task, TaskPriority, TaskStatus
from app.database.repositories.tasks import TaskRepository
from app.services import timeutil

TITLE_MAX_LEN = 200
DESCRIPTION_MAX_LEN = 2000

TaskFilter = Literal["today", "tomorrow", "week", "overdue", "open", "completed", "cancelled", "all"]
TASK_FILTERS: tuple[str, ...] = ("today", "tomorrow", "week", "overdue", "open", "completed", "cancelled", "all")

_UNSET = object()


class TaskError(Exception):
    """Message is safe to show to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidTask(TaskError):
    pass


class TaskNotFound(TaskError):
    pass


class TaskService:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._repo = TaskRepository(db)

    # --- writes ---

    def create_task(
        self,
        title: str,
        *,
        description: str = "",
        due_at: str | None = None,
        priority: str = "normal",
        remind_at: str | None = None,
    ) -> Task:
        due_utc = _valid_moment(due_at, "due date")
        remind_utc = _valid_moment(remind_at, "reminder time")
        _check_reminder_order(due_utc, remind_utc)
        return self._repo.create(
            _valid_title(title),
            _valid_description(description),
            due_utc,
            priority=_valid_priority(priority),
            remind_at=remind_utc,
        )

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        due_at: str | None | object = _UNSET,
        priority: str | None = None,
        remind_at: str | None | object = _UNSET,
    ) -> Task:
        """Change the given fields. Pass `due_at=None` or `remind_at=None`
        explicitly to clear them; omit to leave unchanged."""
        current = self._repo.get(task_id)
        if current is None:
            raise TaskNotFound("I couldn't find that task.")

        changes: dict[str, object] = {}
        if title is not None:
            changes["title"] = _valid_title(title)
        if description is not None:
            changes["description"] = _valid_description(description)
        if priority is not None:
            changes["priority"] = _valid_priority(priority)
        if due_at is not _UNSET:
            changes["due_at"] = _valid_moment(due_at, "due date")  # type: ignore[arg-type]
        if remind_at is not _UNSET:
            changes["remind_at"] = _valid_moment(remind_at, "reminder time")  # type: ignore[arg-type]
        if not changes:
            raise InvalidTask("Nothing to change.")

        due_final = changes.get("due_at", current.due_at)
        remind_final = changes.get("remind_at", current.remind_at)
        _check_reminder_order(due_final, remind_final)  # type: ignore[arg-type]

        updated = self._repo.update(task_id, **changes)
        if updated is None:
            raise TaskNotFound("I couldn't find that task.")
        return updated

    def complete_task(self, task_id: str) -> Task:
        """Mark done. The row is kept, with `completed_at` set, so finished
        work stays in history."""
        return self._set_status(task_id, "completed")

    def cancel_task(self, task_id: str) -> Task:
        return self._set_status(task_id, "cancelled")

    def reopen_task(self, task_id: str) -> Task:
        return self._set_status(task_id, "open")

    def _set_status(self, task_id: str, status: TaskStatus) -> Task:
        record = self._repo.set_status(task_id, status)
        if record is None:
            raise TaskNotFound("I couldn't find that task.")
        return record

    # --- reads ---

    def get_task(self, task_id: str) -> Task:
        record = self._repo.get(task_id)
        if record is None:
            raise TaskNotFound("I couldn't find that task.")
        return record

    def list_tasks(self, task_filter: str = "open", *, limit: int = 200) -> list[Task]:
        """Tasks for a named window. Day and week boundaries are local."""
        window = _valid_filter(task_filter)
        if window == "today":
            start, end = timeutil.local_day_range()
            return self._repo.due_between(start, end)
        if window == "tomorrow":
            start, end = timeutil.local_day_range(1)
            return self._repo.due_between(start, end)
        if window == "week":
            start, end = timeutil.local_week_range()
            return self._repo.due_between(start, end)
        if window == "overdue":
            return self._repo.overdue(timeutil.now_utc_iso())
        if window == "all":
            return self._repo.list(limit=limit)
        return self._repo.list(status=window, limit=limit)  # open | completed | cancelled

    def search_tasks(self, text: str, *, status: TaskStatus | None = "open") -> list[Task]:
        return self._repo.search(text, status=status)

    def due_reminders(self) -> list[Task]:
        """Open tasks whose reminder time has passed. Nothing consumes this
        yet; proactive notifications are a later step."""
        return self._repo.due_for_reminder(timeutil.now_utc_iso())


# --- validation ---


def _valid_title(title: str) -> str:
    value = " ".join(title.split())
    if not value:
        raise InvalidTask("A task needs a title.")
    if len(value) > TITLE_MAX_LEN:
        raise InvalidTask(f"The title must be at most {TITLE_MAX_LEN} characters.")
    return value


def _valid_description(description: str) -> str:
    value = description.strip()
    if len(value) > DESCRIPTION_MAX_LEN:
        raise InvalidTask(f"The description must be at most {DESCRIPTION_MAX_LEN} characters.")
    return value


def _valid_priority(priority: str) -> TaskPriority:
    value = priority.strip().lower()
    if value not in TASK_PRIORITIES:
        raise InvalidTask(f"Priority must be one of: {', '.join(TASK_PRIORITIES)}.")
    return value  # type: ignore[return-value]


def _valid_status(status: str) -> TaskStatus:
    value = status.strip().lower()
    if value not in TASK_STATUSES:
        raise InvalidTask(f"Status must be one of: {', '.join(TASK_STATUSES)}.")
    return value  # type: ignore[return-value]


def _valid_filter(task_filter: str) -> str:
    value = task_filter.strip().lower()
    if value not in TASK_FILTERS:
        raise InvalidTask(f"Unknown list: {', '.join(TASK_FILTERS)}.")
    return value


def _valid_moment(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    try:
        return timeutil.parse_to_utc_iso(value, label=label)
    except timeutil.TimeError as err:
        raise InvalidTask(str(err)) from err


def _check_reminder_order(due_utc: str | None, remind_utc: str | None) -> None:
    if due_utc and remind_utc and remind_utc > due_utc:
        raise InvalidTask("The reminder would come after the task is due.")
