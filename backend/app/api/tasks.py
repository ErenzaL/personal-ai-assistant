"""Task API. Thin: validation and SQL live in the service and repository."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_db
from app.database.models import Task, TaskItem
from app.services.tasks import InvalidTask, TaskError, TaskItemNotFound, TaskNotFound, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

_STATUS = {InvalidTask: 422, TaskNotFound: 404, TaskItemNotFound: 404}


def _http(err: TaskError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(type(err), 400), detail=err.message)


class TaskItemOut(BaseModel):
    id: str
    task_id: str
    text: str
    is_completed: bool
    position: int
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, item: TaskItem) -> "TaskItemOut":
        return cls(**item.__dict__)


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    due_at: str | None
    priority: str
    status: str
    remind_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    category: str
    items: list[TaskItemOut]

    @classmethod
    def from_model(cls, t: Task, items: list[TaskItem]) -> "TaskOut":
        return cls(**t.__dict__, items=[TaskItemOut.from_model(i) for i in items])


class DeletedOut(BaseModel):
    deleted: bool


def _out(service: TaskService, task: Task) -> TaskOut:
    return TaskOut.from_model(task, service.list_items(task.id))


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    """Local-time ISO 8601, e.g. 2026-09-15T18:00:00. Stored as UTC."""
    due_at: str | None = None
    priority: str = "normal"
    remind_at: str | None = None
    category: str = ""
    """Checklist items to create alongside the task, in order."""
    items: list[str] = Field(default_factory=list, max_length=50)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_at: str | None = None
    priority: str | None = None
    remind_at: str | None = None
    category: str | None = None
    """Include "due_at"/"remind_at" here to clear them rather than skip them."""
    clear: list[str] = Field(default_factory=list)


class TaskItemCreate(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class TaskItemUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=200)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    filter: str = Query(default="open", description="today|tomorrow|week|upcoming|overdue|open|completed|cancelled|all"),
    db: sqlite3.Connection = Depends(get_db),
) -> list[TaskOut]:
    try:
        service = TaskService(db)
        return [_out(service, t) for t in service.list_tasks(filter)]
    except TaskError as err:
        raise _http(err) from err


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        record = service.create_task(
            body.title,
            description=body.description,
            due_at=body.due_at,
            priority=body.priority,
            remind_at=body.remind_at,
            category=body.category,
            items=body.items,
        )
    except TaskError as err:
        raise _http(err) from err
    return _out(service, record)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        return _out(service, service.get_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskUpdate, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    kwargs: dict[str, object] = {
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "category": body.category,
    }
    if body.due_at is not None or "due_at" in body.clear:
        kwargs["due_at"] = None if "due_at" in body.clear else body.due_at
    if body.remind_at is not None or "remind_at" in body.clear:
        kwargs["remind_at"] = None if "remind_at" in body.clear else body.remind_at
    try:
        return _out(service, service.update_task(task_id, **kwargs))  # type: ignore[arg-type]
    except TaskError as err:
        raise _http(err) from err


@router.delete("/{task_id}", response_model=DeletedOut)
def delete_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> DeletedOut:
    """Hard delete. Not offered as a casual action anywhere in the desktop
    app; kept for API completeness (see `TaskService.delete_task`)."""
    try:
        TaskService(db).delete_task(task_id)
    except TaskError as err:
        raise _http(err) from err
    return DeletedOut(deleted=True)


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    """Mark done. The task is kept in history, never deleted."""
    service = TaskService(db)
    try:
        return _out(service, service.complete_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        return _out(service, service.cancel_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        return _out(service, service.reopen_task(task_id))
    except TaskError as err:
        raise _http(err) from err


# --- checklist items -----------------------------------------------------------


@router.post("/{task_id}/items", response_model=TaskOut, status_code=201)
def add_item(task_id: str, body: TaskItemCreate, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        service.add_item(task_id, body.text)
        return _out(service, service.get_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.patch("/{task_id}/items/{item_id}", response_model=TaskOut)
def update_item(
    task_id: str, item_id: str, body: TaskItemUpdate, db: sqlite3.Connection = Depends(get_db)
) -> TaskOut:
    service = TaskService(db)
    try:
        service.update_item(task_id, item_id, text=body.text)
        return _out(service, service.get_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/items/{item_id}/complete", response_model=TaskOut)
def complete_item(task_id: str, item_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        service.complete_item(task_id, item_id)
        return _out(service, service.get_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/items/{item_id}/reopen", response_model=TaskOut)
def reopen_item(task_id: str, item_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    service = TaskService(db)
    try:
        service.reopen_item(task_id, item_id)
        return _out(service, service.get_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.delete("/{task_id}/items/{item_id}", response_model=DeletedOut)
def delete_item(task_id: str, item_id: str, db: sqlite3.Connection = Depends(get_db)) -> DeletedOut:
    try:
        TaskService(db).delete_item(task_id, item_id)
    except TaskError as err:
        raise _http(err) from err
    return DeletedOut(deleted=True)
