"""Assistant settings. Thin: validation lives in the preferences service."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db
from app.services.preferences import (
    NAME_MAX_LEN,
    REMINDER_MINUTES_MAX,
    REMINDER_MINUTES_MIN,
    RESPONSE_STYLES,
    AssistantPreferences,
    InvalidPreference,
    PreferencesService,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    assistant_name: str
    response_style: str
    available_styles: list[str]
    """EventKit identifier chosen for new events; null means the macOS default."""
    default_calendar_id: str | None = None
    reminder_minutes: int
    calendar_notifications: bool
    edge_activation: bool
    memory_enabled: bool

    @classmethod
    def from_model(cls, prefs: AssistantPreferences) -> "SettingsOut":
        return cls(
            assistant_name=prefs.assistant_name,
            response_style=prefs.response_style,
            available_styles=list(RESPONSE_STYLES),
            default_calendar_id=prefs.default_calendar_id,
            reminder_minutes=prefs.reminder_minutes,
            calendar_notifications=prefs.calendar_notifications,
            edge_activation=prefs.edge_activation,
            memory_enabled=prefs.memory_enabled,
        )


class SettingsUpdate(BaseModel):
    assistant_name: str | None = Field(default=None, max_length=NAME_MAX_LEN)
    response_style: str | None = None
    """Send "" to clear the choice and fall back to the macOS default."""
    default_calendar_id: str | None = Field(default=None, max_length=256)
    reminder_minutes: int | None = Field(default=None, ge=REMINDER_MINUTES_MIN, le=REMINDER_MINUTES_MAX)
    calendar_notifications: bool | None = None
    edge_activation: bool | None = None
    memory_enabled: bool | None = None


@router.get("", response_model=SettingsOut)
def get_settings_(db: sqlite3.Connection = Depends(get_db)) -> SettingsOut:
    return SettingsOut.from_model(PreferencesService(db).get())


@router.patch("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: sqlite3.Connection = Depends(get_db)) -> SettingsOut:
    try:
        prefs = PreferencesService(db).update(
            assistant_name=body.assistant_name,
            response_style=body.response_style,
            default_calendar_id=body.default_calendar_id,
            reminder_minutes=body.reminder_minutes,
            calendar_notifications=body.calendar_notifications,
            edge_activation=body.edge_activation,
            memory_enabled=body.memory_enabled,
        )
    except InvalidPreference as err:
        raise HTTPException(status_code=422, detail=err.message) from err
    return SettingsOut.from_model(prefs)
