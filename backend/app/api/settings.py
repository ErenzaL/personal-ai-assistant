"""Assistant settings. Thin: validation lives in the preferences service."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db
from app.services.preferences import (
    NAME_MAX_LEN,
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

    @classmethod
    def from_model(cls, prefs: AssistantPreferences) -> "SettingsOut":
        return cls(
            assistant_name=prefs.assistant_name,
            response_style=prefs.response_style,
            available_styles=list(RESPONSE_STYLES),
        )


class SettingsUpdate(BaseModel):
    assistant_name: str | None = Field(default=None, max_length=NAME_MAX_LEN)
    response_style: str | None = None


@router.get("", response_model=SettingsOut)
def get_settings_(db: sqlite3.Connection = Depends(get_db)) -> SettingsOut:
    return SettingsOut.from_model(PreferencesService(db).get())


@router.patch("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: sqlite3.Connection = Depends(get_db)) -> SettingsOut:
    try:
        prefs = PreferencesService(db).update(
            assistant_name=body.assistant_name, response_style=body.response_style
        )
    except InvalidPreference as err:
        raise HTTPException(status_code=422, detail=err.message) from err
    return SettingsOut.from_model(prefs)
