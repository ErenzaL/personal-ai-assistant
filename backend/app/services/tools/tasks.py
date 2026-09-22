"""The task tools: list, create, update, complete, cancel, complete_item.

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

from app.database.models import Task, TaskItem
from app.services import timeutil
from app.services.tasks import TaskError, TaskService
from app.services.tools.base import ToolOutcome, ToolSpec

MAX_CANDIDATES = 5

TASKS_LIST = "tasks.list"
TASKS_CREATE = "tasks.create"
TASKS_UPDATE = "tasks.update"
TASKS_COMPLETE = "tasks.complete"
TASKS_CANCEL = "tasks.cancel"
TASKS_COMPLETE_ITEM = "tasks.complete_item"
TASKS_OPEN_PANEL = "tasks.open_panel"

TaskFilterArg = Literal["today", "tomorrow", "week", "upcoming", "overdue", "open", "completed", "cancelled", "all"]
PriorityArg = Literal["low", "normal", "high"]


# --- argument models ---------------------------------------------------------


class ListArgs(BaseModel):
    filter: TaskFilterArg = "open"
    """Whether the panel's "open this list" button is worth offering after
    answering. True for an open-ended browse ("show my tasks", "what do I
    have today"); False for a specific fact the answer already settles
    ("when is X due", "how many tasks do I have", "is X finished")."""
    offer_panel: bool = True


class OpenPanelArgs(BaseModel):
    """The user explicitly asked to navigate to the task interface itself
    ("open my tasks", "open the task manager", "take me to my tasks") rather
    than asking a question about their tasks. Opens immediately -- no
    summary needed, just a brief acknowledgement."""

    filter: TaskFilterArg = "open"


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    """Local time, "YYYY-MM-DDTHH:MM:SS". Resolve relative dates before calling."""
    due_at: str | None = None
    remind_at: str | None = None
    priority: PriorityArg = "normal"
    """Only set when the wording clearly implies one ("for school" -> "School"). Never invented."""
    category: str | None = Field(default=None, max_length=60)


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


class ItemRefArgs(BaseModel):
    """Identifies one checklist item by wording (optionally narrowed to one
    task by wording too), or by item id from a previous result. Deliberately
    NOT a TaskRefArgs subclass: "I finished the plots" never names a task,
    and requiring `match` would force the model to invent one."""

    match: str | None = Field(default=None, max_length=200)
    task_id: str | None = None
    item_match: str | None = Field(default=None, max_length=200)
    item_id: str | None = None

    @model_validator(mode="after")
    def _need_one(self) -> "ItemRefArgs":
        if not (self.item_match and self.item_match.strip()) and not (self.item_id and self.item_id.strip()):
            raise ValueError("either item_match or item_id is required")
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
    if task.category:
        body["category"] = task.category
    if task.description:
        body["description"] = task.description
    if with_id:
        body["task_id"] = task.id
    return body


def _item_json(item: TaskItem, *, with_id: bool = False, task: Task | None = None) -> dict[str, object]:
    body: dict[str, object] = {"text": item.text, "completed": item.is_completed}
    if task is not None:
        body["task"] = task.title
    if with_id:
        body["item_id"] = item.id
        if task is not None:
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
                TASKS_LIST,
                "Answer a question about the user's tasks -- how many, what's due, what's overdue, "
                "what to focus on, what's been finished. \"week\" means the next seven days; "
                '"upcoming" means every future or undated open task. This does NOT open anything by '
                "itself: write a short, genuinely useful answer from the real data (a count, the "
                "nearest deadline, an overdue warning, a priority recommendation -- whichever the "
                "question actually calls for), never a line-by-line list.",
                ListArgs,
                self.list_tasks,
            ),
            ToolSpec(
                TASKS_CREATE,
                "Create a task. Give due_at/remind_at as local time, already resolved from words "
                'like "tomorrow evening".',
                CreateArgs,
                self.create_task,
            ),
            ToolSpec(
                TASKS_UPDATE,
                "Change an existing open task: move its due date, rename it, or set its priority.",
                UpdateArgs,
                self.update_task,
            ),
            ToolSpec(TASKS_COMPLETE, "Mark an entire existing open task as done.", TaskRefArgs, self.complete_task),
            ToolSpec(TASKS_CANCEL, "Cancel an existing open task the user no longer wants.", TaskRefArgs, self.cancel_task),
            ToolSpec(
                TASKS_COMPLETE_ITEM,
                "Mark ONE checklist item within a task as done -- not the whole task. Use this when "
                'the user names a specific step or sub-part ("I finished the plots", "done with '
                'chapter 2.4"), not the task as a whole.',
                ItemRefArgs,
                self.complete_item,
            ),
            ToolSpec(
                TASKS_OPEN_PANEL,
                'The user explicitly wants to navigate to the task interface itself ("open my '
                'tasks", "open the task manager", "take me to my tasks", "open today\'s task '
                'page") -- a UI command, not a question. Never use this for a question about what '
                "tasks exist or what's due; use tasks.list for that instead.",
                OpenPanelArgs,
                self.open_panel,
            ),
        ]

    # --- handlers ---

    def open_panel(self, args: OpenPanelArgs) -> ToolOutcome:
        """Nothing to look up or change -- opening the panel is a desktop-app
        action the backend only names, computed deterministically from
        `filter` in `api/chat.py`, never from anything written in prose."""
        return ToolOutcome.success(TASKS_OPEN_PANEL, opened=True, filter=args.filter)

    def list_tasks(self, args: ListArgs) -> ToolOutcome:
        try:
            items = self._tasks.list_tasks(args.filter)
        except TaskError as err:
            return ToolOutcome.failure(TASKS_LIST, "invalid_arguments", err.message)
        return ToolOutcome.success(
            TASKS_LIST,
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
                category=args.category or "",
            )
        except TaskError as err:
            return ToolOutcome.failure(TASKS_CREATE, "rejected", err.message)
        return ToolOutcome.success(TASKS_CREATE, created=True, task=_task_json(task))

    def update_task(self, args: UpdateArgs) -> ToolOutcome:
        found = self._resolve(TASKS_UPDATE, args)
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
            return ToolOutcome.failure(TASKS_UPDATE, "rejected", err.message)
        return ToolOutcome.success(TASKS_UPDATE, updated=True, task=_task_json(task))

    def complete_task(self, args: TaskRefArgs) -> ToolOutcome:
        return self._transition(TASKS_COMPLETE, args, self._tasks.complete_task, "completed")

    def cancel_task(self, args: TaskRefArgs) -> ToolOutcome:
        return self._transition(TASKS_CANCEL, args, self._tasks.cancel_task, "cancelled")

    def _transition(self, name: str, args: TaskRefArgs, action, key: str) -> ToolOutcome:
        found = self._resolve(name, args)
        if isinstance(found, ToolOutcome):
            return found
        try:
            task = action(found.id)
        except TaskError as err:
            return ToolOutcome.failure(name, "rejected", err.message)
        return ToolOutcome.success(name, **{key: True, "task": _task_json(task)})

    def complete_item(self, args: ItemRefArgs) -> ToolOutcome:
        found = self._resolve_item(TASKS_COMPLETE_ITEM, args)
        if isinstance(found, ToolOutcome):
            return found
        task, item = found
        already_completed = item.is_completed
        try:
            updated = self._tasks.complete_item(task.id, item.id)
        except TaskError as err:
            return ToolOutcome.failure(TASKS_COMPLETE_ITEM, "rejected", err.message)
        return ToolOutcome.success(
            TASKS_COMPLETE_ITEM,
            completed=True,
            already_completed=already_completed,
            item=_item_json(updated, task=task),
        )

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

    def _resolve_item(self, tool: str, args: ItemRefArgs) -> tuple[Task, TaskItem] | ToolOutcome:
        """Find the one checklist item the user means, optionally narrowed to
        one task first when the wording (or an earlier task_id) names it."""
        if args.item_id:
            # An id echoed back from an earlier ambiguous result: the task
            # is whichever one actually owns it, not necessarily `match`.
            pool = self._tasks.list_tasks("open")
            for task in pool:
                for item in self._tasks.list_items(task.id):
                    if item.id == args.item_id.strip():
                        return task, item
            return ToolOutcome.failure(tool, "not_found", "That checklist item no longer exists.")

        if args.match or args.task_id:
            task = self._resolve(tool, TaskRefArgs(match=args.match, task_id=args.task_id))
            if isinstance(task, ToolOutcome):
                return task
            candidate_tasks = [task]
        else:
            candidate_tasks = self._tasks.list_tasks("open")

        if not candidate_tasks:
            return ToolOutcome.failure(tool, "not_found", "There are no open tasks.")

        # Completed items stay in the pool (not just open ones): re-matching
        # "I finished the plots" against an already-done item is exactly how
        # a duplicate completion is told apart from a genuine not-found, so
        # the handler can answer "already done" instead of a false negative.
        terms = _terms(args.item_match or "")
        scored: list[tuple[int, Task, TaskItem]] = []
        for task in candidate_tasks:
            for item in self._tasks.list_items(task.id):
                score = sum(1 for t in terms if t in _terms(item.text))
                if score:
                    scored.append((score, task, item))

        if not scored:
            return ToolOutcome.failure(
                tool, "not_found", "No checklist item matches that wording."
            )

        scored.sort(key=lambda triple: (-triple[0], triple[2].position))
        best = scored[0][0]
        tied = [(task, item) for score, task, item in scored if score == best]
        if len(tied) > 1:
            return ToolOutcome.failure(
                tool,
                "ambiguous",
                "More than one checklist item matches; ask the user which one they mean.",
                candidates=[_item_json(item, with_id=True, task=task) for task, item in tied[:MAX_CANDIDATES]],
            )
        return tied[0]
