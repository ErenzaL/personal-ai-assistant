"""Task API. Thin: validation and SQL live in the service and repository."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_db
from app.database.models import Task
from app.services.tasks import InvalidTask, TaskError, TaskNotFound, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

_STATUS = {InvalidTask: 422, TaskNotFound: 404}


def _http(err: TaskError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(type(err), 400), detail=err.message)


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

    @classmethod
    def from_model(cls, t: Task) -> "TaskOut":
        return cls(**t.__dict__)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    """Local-time ISO 8601, e.g. 2026-09-15T18:00:00. Stored as UTC."""
    due_at: str | None = None
    priority: str = "normal"
    remind_at: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_at: str | None = None
    priority: str | None = None
    remind_at: str | None = None
    """Include "due_at"/"remind_at" here to clear them rather than skip them."""
    clear: list[str] = Field(default_factory=list)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    filter: str = Query(default="open", description="today|tomorrow|week|overdue|open|completed|cancelled|all"),
    db: sqlite3.Connection = Depends(get_db),
) -> list[TaskOut]:
    try:
        return [TaskOut.from_model(t) for t in TaskService(db).list_tasks(filter)]
    except TaskError as err:
        raise _http(err) from err


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    try:
        record = TaskService(db).create_task(
            body.title,
            description=body.description,
            due_at=body.due_at,
            priority=body.priority,
            remind_at=body.remind_at,
        )
    except TaskError as err:
        raise _http(err) from err
    return TaskOut.from_model(record)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    try:
        return TaskOut.from_model(TaskService(db).get_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskUpdate, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    kwargs: dict[str, object] = {
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
    }
    if body.due_at is not None or "due_at" in body.clear:
        kwargs["due_at"] = None if "due_at" in body.clear else body.due_at
    if body.remind_at is not None or "remind_at" in body.clear:
        kwargs["remind_at"] = None if "remind_at" in body.clear else body.remind_at
    try:
        return TaskOut.from_model(TaskService(db).update_task(task_id, **kwargs))  # type: ignore[arg-type]
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    """Mark done. The task is kept in history, never deleted."""
    try:
        return TaskOut.from_model(TaskService(db).complete_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    try:
        return TaskOut.from_model(TaskService(db).cancel_task(task_id))
    except TaskError as err:
        raise _http(err) from err


@router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen_task(task_id: str, db: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    try:
        return TaskOut.from_model(TaskService(db).reopen_task(task_id))
    except TaskError as err:
        raise _http(err) from err
