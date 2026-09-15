"""Assistant preferences: how the assistant presents itself.

Stored as rows in the `settings` table, so they survive restarts and are
separate from personal memory (facts about the user) and from conversation
history (what was said).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.database.repositories import SettingsRepository
from app.services.llm.prompts import DEFAULT_ASSISTANT_NAME

ASSISTANT_NAME_KEY = "assistant_name"
RESPONSE_STYLE_KEY = "response_style"
DEFAULT_CALENDAR_KEY = "default_calendar_id"
REMINDER_MINUTES_KEY = "reminder_minutes"
CALENDAR_NOTIFICATIONS_KEY = "calendar_notifications"
EDGE_ACTIVATION_KEY = "edge_activation"
MEMORY_ENABLED_KEY = "memory_enabled"

DEFAULT_NAME = DEFAULT_ASSISTANT_NAME
NAME_MAX_LEN = 24
DEFAULT_REMINDER_MINUTES = 10
REMINDER_MINUTES_MIN = 1
REMINDER_MINUTES_MAX = 120

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
    """EventKit calendar identifier for new events. None means "whatever macOS
    uses by default"; the identifier itself is opaque to us."""
    default_calendar_id: str | None = None
    """Minutes before an event that the desktop app alerts."""
    reminder_minutes: int = DEFAULT_REMINDER_MINUTES
    """Whether calendar reminders alert at all."""
    calendar_notifications: bool = True
    """Whether the mascot appears when the cursor touches the bottom-right edge."""
    edge_activation: bool = True
    """Whether ordinary conversation is scanned for things worth remembering.
    Off stops new memories being created; existing ones stay and are still
    used to answer, and can still be reviewed, edited or forgotten."""
    memory_enabled: bool = True

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
        calendar_id = self._settings.get(DEFAULT_CALENDAR_KEY)
        minutes = self._settings.get(REMINDER_MINUTES_KEY, DEFAULT_REMINDER_MINUTES)
        notify = self._settings.get(CALENDAR_NOTIFICATIONS_KEY, True)
        edge = self._settings.get(EDGE_ACTIVATION_KEY, True)
        memory_enabled = self._settings.get(MEMORY_ENABLED_KEY, True)
        return AssistantPreferences(
            assistant_name=name if isinstance(name, str) and name.strip() else DEFAULT_NAME,
            response_style=style if style in RESPONSE_STYLES else DEFAULT_STYLE,
            default_calendar_id=calendar_id if isinstance(calendar_id, str) and calendar_id else None,
            reminder_minutes=minutes if _minutes_ok(minutes) else DEFAULT_REMINDER_MINUTES,
            calendar_notifications=notify if isinstance(notify, bool) else True,
            edge_activation=edge if isinstance(edge, bool) else True,
            memory_enabled=memory_enabled if isinstance(memory_enabled, bool) else True,
        )

    def update(
        self,
        *,
        assistant_name: str | None = None,
        response_style: str | None = None,
        default_calendar_id: str | None = None,
        reminder_minutes: int | None = None,
        calendar_notifications: bool | None = None,
        edge_activation: bool | None = None,
        memory_enabled: bool | None = None,
    ) -> AssistantPreferences:
        if assistant_name is not None:
            self._settings.set(ASSISTANT_NAME_KEY, _valid_name(assistant_name))
        if response_style is not None:
            self._settings.set(RESPONSE_STYLE_KEY, _valid_style(response_style))
        if default_calendar_id is not None:
            # Empty string clears the choice and falls back to the macOS default.
            value = default_calendar_id.strip()
            if value:
                self._settings.set(DEFAULT_CALENDAR_KEY, value)
            else:
                self._settings.delete(DEFAULT_CALENDAR_KEY)
        if reminder_minutes is not None:
            self._settings.set(REMINDER_MINUTES_KEY, _valid_minutes(reminder_minutes))
        if calendar_notifications is not None:
            self._settings.set(CALENDAR_NOTIFICATIONS_KEY, bool(calendar_notifications))
        if edge_activation is not None:
            self._settings.set(EDGE_ACTIVATION_KEY, bool(edge_activation))
        if memory_enabled is not None:
            self._settings.set(MEMORY_ENABLED_KEY, bool(memory_enabled))
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


def _minutes_ok(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and REMINDER_MINUTES_MIN <= value <= REMINDER_MINUTES_MAX


def _valid_minutes(value: int) -> int:
    if not _minutes_ok(value):
        raise InvalidPreference(
            f"Reminder minutes must be a whole number from {REMINDER_MINUTES_MIN} to {REMINDER_MINUTES_MAX}."
        )
    return value
