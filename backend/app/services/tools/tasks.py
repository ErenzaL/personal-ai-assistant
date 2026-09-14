"""The five task tools: list, create, update, complete, cancel.

Each one validates its arguments (Pydantic), calls the deterministic
`TaskService`, and returns structured JSON. Nothing here writes prose: the
assistant turns these results into an answer, and may only claim something
happened when `ok` is true.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.database.models import Task
from app.services import timeutil
from app.services.tasks import TaskError, TaskService
from app.services.tools.base import ToolOutcome, ToolSpec

MAX_CANDIDATES = 5

TaskFilterArg = Literal["today", "tomorrow", "week", "overdue", "open", "completed", "cancelled", "all"]
PriorityArg = Literal["low", "normal", "high"]


# --- argument models ---------------------------------------------------------


class ListArgs(BaseModel):
    filter: TaskFilterArg = "open"


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    """Local time, "YYYY-MM-DDTHH:MM:SS". Resolve relative dates before calling."""
    due_at: str | None = None
    remind_at: str | None = None
    priority: PriorityArg = "normal"


class TaskRefArgs(BaseModel):
    """Identifies an existing task by wording, or by id from a previous result."""

    match: str | None = Field(default=None, max_length=200)
    task_id: str | None = None

    @model_validator(mode="after")
    def _need_one(self) -> "TaskRefArgs":
        if not (self.match and self.match.strip()) and not (self.task_id and self.task_id.strip()):
            raise ValueError("either match or task_id is required")
        return self


class UpdateArgs(TaskRefArgs):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_at: str | None = None
    remind_at: str | None = None
    priority: PriorityArg | None = None

    @model_validator(mode="after")
    def _need_change(self) -> "UpdateArgs":
        if self.title is None and self.due_at is None and self.remind_at is None and self.priority is None:
            raise ValueError("nothing to change")
        return self


# --- serialisation -----------------------------------------------------------


def _task_json(task: Task, *, with_id: bool = False) -> dict[str, object]:
    """Compact view for the prompt: due dates already in local wording."""
    body: dict[str, object] = {"title": task.title, "status": task.status}
    if task.due_at:
        body["due"] = timeutil.format_local(task.due_at)
    if task.remind_at:
        body["reminder"] = timeutil.format_local(task.remind_at)
    if task.priority != "normal":
        body["priority"] = task.priority
    if task.description:
        body["description"] = task.description
    if with_id:
        body["task_id"] = task.id
    return body


# --- matching ----------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "my", "me", "i", "to", "of", "and", "or", "in", "on", "for", "with", "that",
    "this", "it", "is", "are", "do", "you", "your", "please", "task", "tasks", "todo", "item",
}


def _stem(word: str) -> str:
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not word.endswith("ss"):
            return word[: -len(suffix)] + replacement
    return word


def _terms(text: str) -> list[str]:
    out = [
        _stem(piece)
        for piece in re.split(r"[^\w]+", text.lower())
        if len(piece) >= 2 and piece not in _STOPWORDS
    ]
    return list(dict.fromkeys(out))


class TaskTools:
    """Builds the task tool specs over one database connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._tasks = TaskService(db)

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "tasks.list",
                'List the user\'s tasks in one window. "week" means the next seven days.',
                ListArgs,
                self.list_tasks,
            ),
            ToolSpec(
                "tasks.create",
                "Create a task. Give due_at/remind_at as local time, already resolved from words "
                'like "tomorrow evening".',
                CreateArgs,
                self.create_task,
            ),
            ToolSpec(
                "tasks.update",
                "Change an existing open task: move its due date, rename it, or set its priority.",
                UpdateArgs,
                self.update_task,
            ),
            ToolSpec("tasks.complete", "Mark an existing open task as done.", TaskRefArgs, self.complete_task),
            ToolSpec("tasks.cancel", "Cancel an existing open task the user no longer wants.", TaskRefArgs, self.cancel_task),
        ]

    # --- handlers ---

    def list_tasks(self, args: ListArgs) -> ToolOutcome:
        try:
            items = self._tasks.list_tasks(args.filter)
        except TaskError as err:
            return ToolOutcome.failure("tasks.list", "invalid_arguments", err.message)
        return ToolOutcome.success(
            "tasks.list",
            filter=args.filter,
            count=len(items),
            tasks=[_task_json(t) for t in items],
        )

    def create_task(self, args: CreateArgs) -> ToolOutcome:
        try:
            task = self._tasks.create_task(
                args.title,
                description=args.description,
                due_at=args.due_at,
                priority=args.priority,
                remind_at=args.remind_at,
            )
        except TaskError as err:
            return ToolOutcome.failure("tasks.create", "rejected", err.message)
        return ToolOutcome.success("tasks.create", created=True, task=_task_json(task))

    def update_task(self, args: UpdateArgs) -> ToolOutcome:
        found = self._resolve("tasks.update", args)
        if isinstance(found, ToolOutcome):
            return found
        changes: dict[str, object] = {}
        if args.title is not None:
            changes["title"] = args.title
        if args.priority is not None:
            changes["priority"] = args.priority
        if args.due_at is not None:
            changes["due_at"] = args.due_at
        if args.remind_at is not None:
            changes["remind_at"] = args.remind_at
        try:
            task = self._tasks.update_task(found.id, **changes)  # type: ignore[arg-type]
        except TaskError as err:
            return ToolOutcome.failure("tasks.update", "rejected", err.message)
        return ToolOutcome.success("tasks.update", updated=True, task=_task_json(task))

    def complete_task(self, args: TaskRefArgs) -> ToolOutcome:
        return self._transition("tasks.complete", args, self._tasks.complete_task, "completed")

    def cancel_task(self, args: TaskRefArgs) -> ToolOutcome:
        return self._transition("tasks.cancel", args, self._tasks.cancel_task, "cancelled")

    def _transition(self, name: str, args: TaskRefArgs, action, key: str) -> ToolOutcome:
        found = self._resolve(name, args)
        if isinstance(found, ToolOutcome):
            return found
        try:
            task = action(found.id)
        except TaskError as err:
            return ToolOutcome.failure(name, "rejected", err.message)
        return ToolOutcome.success(name, **{key: True, "task": _task_json(task)})

    # --- resolution ---

    def _resolve(self, tool: str, args: TaskRefArgs) -> Task | ToolOutcome:
        """Find the one open task the user means, or explain why we can't."""
        if args.task_id:
            try:
                return self._tasks.get_task(args.task_id.strip())
            except TaskError as err:
                return ToolOutcome.failure(tool, "not_found", err.message)

        pool = self._tasks.list_tasks("open")
        if not pool:
            return ToolOutcome.failure(tool, "not_found", "There are no open tasks.")

        terms = _terms(args.match or "")
        scored = []
        for task in pool:
            hay = _terms(f"{task.title} {task.description}")
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, task))
        if not scored:
            return ToolOutcome.failure(
                tool, "not_found", "No open task matches that wording.", open_count=len(pool)
            )

        scored.sort(key=lambda pair: (-pair[0], pair[1].created_at))
        best = scored[0][0]
        tied = [task for score, task in scored if score == best]
        if len(tied) > 1:
            # Several tasks match equally well: the assistant must ask which.
            return ToolOutcome.failure(
                tool,
                "ambiguous",
                "More than one open task matches; ask the user which one they mean.",
                candidates=[_task_json(t, with_id=True) for t in tied[:MAX_CANDIDATES]],
            )
        return tied[0]
