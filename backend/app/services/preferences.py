"""Assistant preferences: how the assistant presents itself.

Stored as rows in the `settings` table, so they survive restarts and are
separate from personal memory (facts about the user) and from conversation
history (what was said).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.database.repositories import SettingsRepository

ASSISTANT_NAME_KEY = "assistant_name"
RESPONSE_STYLE_KEY = "response_style"

DEFAULT_NAME = "Assistant"
NAME_MAX_LEN = 24

# Each style adds one line to the system instructions. "balanced" adds
# nothing, so the default prompt is exactly the identity prompt.
RESPONSE_STYLES: dict[str, str] = {
    "balanced": "",
    "concise": "Keep replies to one or two sentences unless the user asks for more.",
    "detailed": "Explain your reasoning and give useful background, while staying readable.",
    "friendly": "Use a warm, casual tone, as if talking to a friend.",
}
DEFAULT_STYLE = "balanced"


@dataclass(frozen=True)
class AssistantPreferences:
    assistant_name: str = DEFAULT_NAME
    response_style: str = DEFAULT_STYLE

    @property
    def style_instruction(self) -> str:
        return RESPONSE_STYLES.get(self.response_style, "")


class InvalidPreference(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PreferencesService:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._settings = SettingsRepository(db)

    def get(self) -> AssistantPreferences:
        name = self._settings.get(ASSISTANT_NAME_KEY, DEFAULT_NAME)
        style = self._settings.get(RESPONSE_STYLE_KEY, DEFAULT_STYLE)
        return AssistantPreferences(
            assistant_name=name if isinstance(name, str) and name.strip() else DEFAULT_NAME,
            response_style=style if style in RESPONSE_STYLES else DEFAULT_STYLE,
        )

    def update(self, *, assistant_name: str | None = None, response_style: str | None = None) -> AssistantPreferences:
        if assistant_name is not None:
            self._settings.set(ASSISTANT_NAME_KEY, _valid_name(assistant_name))
        if response_style is not None:
            self._settings.set(RESPONSE_STYLE_KEY, _valid_style(response_style))
        return self.get()


def _valid_name(name: str) -> str:
    value = " ".join(name.split())
    if not value:
        raise InvalidPreference("Name must not be empty.")
    if len(value) > NAME_MAX_LEN:
        raise InvalidPreference(f"Name must be at most {NAME_MAX_LEN} characters.")
    return value


def _valid_style(style: str) -> str:
    value = style.strip().lower()
    if value not in RESPONSE_STYLES:
        raise InvalidPreference(f"Style must be one of: {', '.join(RESPONSE_STYLES)}.")
    return value
