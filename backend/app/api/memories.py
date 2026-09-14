"""Memory API. Thin: validation and SQL live in the service and repository."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_db
from app.database.models import MEMORY_CATEGORIES, Memory
from app.services.memory import InvalidMemory, MemoryConflict, MemoryError, MemoryNotFound, MemoryService

router = APIRouter(prefix="/memories", tags=["memories"])

_STATUS = {InvalidMemory: 422, MemoryNotFound: 404, MemoryConflict: 409}


def _http(err: MemoryError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(type(err), 400), detail=err.message)


class MemoryOut(BaseModel):
    id: str
    category: str
    key: str
    content: str
    source: str
    confidence: float
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, m: Memory) -> "MemoryOut":
        return cls(**m.__dict__)


class MemoryCreate(BaseModel):
    category: str
    """Optional: derived from the content when omitted."""
    key: str | None = None
    content: str = Field(min_length=1, max_length=1000)
    source: str = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@router.get("/categories", response_model=list[str])
def categories() -> list[str]:
    return list(MEMORY_CATEGORIES)


@router.get("", response_model=list[MemoryOut])
def list_or_search(
    q: str | None = Query(default=None, description="case-insensitive match on key/content"),
    category: str | None = None,
    key: str | None = None,
    include_inactive: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> list[MemoryOut]:
    service = MemoryService(db)
    try:
        if q or key:
            items = service.search_memories(q, category=category, key=key, include_inactive=include_inactive)
        else:
            items = service.list_memories(category=category, include_inactive=include_inactive)
    except MemoryError as err:
        raise _http(err) from err
    return [MemoryOut.from_model(m) for m in items]


@router.post("", response_model=MemoryOut, status_code=201)
def create(body: MemoryCreate, db: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    try:
        record = MemoryService(db).create_memory(
            body.category, body.key, body.content, source=body.source, confidence=body.confidence
        )
    except MemoryError as err:
        raise _http(err) from err
    return MemoryOut.from_model(record)


class DeactivatedCount(BaseModel):
    deactivated: int


@router.post("/deactivate-all", response_model=DeactivatedCount)
def deactivate_all(category: str | None = None, db: sqlite3.Connection = Depends(get_db)) -> DeactivatedCount:
    """Soft-delete every active memory. Rows are kept and can be reactivated."""
    try:
        return DeactivatedCount(deactivated=MemoryService(db).deactivate_all(category=category))
    except MemoryError as err:
        raise _http(err) from err


@router.get("/{memory_id}", response_model=MemoryOut)
def get(memory_id: str, db: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    try:
        return MemoryOut.from_model(MemoryService(db).get_memory(memory_id))
    except MemoryError as err:
        raise _http(err) from err


@router.patch("/{memory_id}", response_model=MemoryOut)
def update(memory_id: str, body: MemoryUpdate, db: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    try:
        record = MemoryService(db).update_memory(
            memory_id, content=body.content, source=body.source, confidence=body.confidence
        )
    except MemoryError as err:
        raise _http(err) from err
    return MemoryOut.from_model(record)


@router.delete("/{memory_id}", response_model=MemoryOut)
def deactivate(memory_id: str, db: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    """Soft delete: marks the memory inactive. The row is kept."""
    try:
        return MemoryOut.from_model(MemoryService(db).deactivate_memory(memory_id))
    except MemoryError as err:
        raise _http(err) from err


@router.post("/{memory_id}/activate", response_model=MemoryOut)
def activate(memory_id: str, db: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    try:
        return MemoryOut.from_model(MemoryService(db).reactivate_memory(memory_id))
    except MemoryError as err:
        raise _http(err) from err
