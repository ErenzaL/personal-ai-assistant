"""The calendar tool.

Unlike the task tools this one does **not** run here. Calendar access lives in
the macOS layer through EventKit, so the tool is dispatched to the desktop
app, which executes it natively and posts the structured result back. The
backend never touches a calendar or any credential.

This module therefore defines only the contract (name, description, typed
arguments) and how a returned result is rendered for the model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services import timeutil
from app.services.tools.base import Execution, ToolSpec

CALENDAR_READ = "calendar.read"
CALENDAR_PROPOSE = "calendar.propose_event"

# Used when the user gives a start time but no duration.
DEFAULT_DURATION_MINUTES = 60

# Cap what reaches the prompt: a wide range ("when is my next appointment?")
# can match a lot, and only the first few matter.
MAX_EVENTS = 40


class ProposeArgs(BaseModel):
    """A new event, as understood from the user's words.

    `end` and `duration_minutes` are alternatives; when neither is given the
    app applies `DEFAULT_DURATION_MINUTES`. The end time is always computed in
    code, never by the model.
    """

    title: str = Field(min_length=1, max_length=200)
    """Local-time ISO 8601, e.g. 2026-09-15T19:00:00."""
    start: str = Field(min_length=4, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    duration_minutes: int | None = Field(default=None, ge=1, le=60 * 24)
    """What the user called the calendar ("personal", "work"); matched by name."""
    calendar_name: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class ReadArgs(BaseModel):
    """Local-time ISO 8601 bounds, resolved by the selector from words like
    "tomorrow" or "Friday afternoon"."""

    start: str = Field(min_length=4, max_length=40)
    end: str = Field(min_length=4, max_length=40)


def calendar_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            CALENDAR_READ,
            "Read the user's calendar between two local datetimes, to answer what they have on, "
            "whether they are free, or when something next happens. Covers every calendar macOS "
            "knows about (iCloud, Google and so on).",
            ReadArgs,
            execution=Execution.CLIENT,
        ),
        ToolSpec(
            CALENDAR_PROPOSE,
            "Prepare a new calendar event from the user's request. This does NOT create it: the "
            "app shows the details for the user to confirm first. Give start as local time; give "
            "duration_minutes when the user states a length (\"for one hour\" -> 60).",
            ProposeArgs,
            execution=Execution.CLIENT,
        ),
    ]


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a raw client result into the compact, local-time shape that
    goes into the prompt. Times arrive as ISO 8601 with an offset."""
    if not result.get("ok"):
        return result
    if result.get("tool") == CALENDAR_PROPOSE:
        return _summarise_proposal(result)

    events = (result.get("data") or {}).get("events") or []
    rendered = []
    for event in events[:MAX_EVENTS]:
        start, end = event.get("start"), event.get("end")
        item: dict[str, Any] = {"title": event.get("title") or "(untitled)"}
        if event.get("all_day"):
            # Only the date is meaningful, so no clock time is shown.
            item["when"] = f"{_date_only(start)} (all day)" if start else "all day"
            item["all_day"] = True
        else:
            item["when"] = timeutil.format_local(_utc(start)) if start else "unknown"
            if end:
                item["until"] = timeutil.to_local(_utc(end)).strftime("%-I:%M %p")
        if event.get("calendar_title"):
            item["calendar"] = event["calendar_title"]
        if event.get("location"):
            item["location"] = event["location"]
        rendered.append(item)

    return {
        "ok": True,
        "tool": result.get("tool", CALENDAR_READ),
        "data": {
            "range": (result.get("data") or {}).get("range"),
            "count": len(events),
            "truncated": len(events) > MAX_EVENTS,
            "events": rendered,
        },
    }


def _summarise_proposal(result: dict[str, Any]) -> dict[str, Any]:
    """A proposed event, in local wording. Nothing has been created: the user
    still has to confirm it in the panel."""
    proposal = (result.get("data") or {}).get("proposal") or {}
    conflicts = [
        {
            "title": c.get("title") or "(untitled)",
            "when": f"{_clock(c.get('start'))}–{_clock(c.get('end'))}",
        }
        for c in proposal.get("conflicts") or []
    ]
    return {
        "ok": True,
        "tool": CALENDAR_PROPOSE,
        "data": {
            "created": False,
            "awaiting_confirmation": True,
            "event": {
                "title": proposal.get("title"),
                "when": _local(proposal.get("start")),
                "until": _clock(proposal.get("end")),
                "calendar": proposal.get("calendarTitle"),
                **({"location": proposal["location"]} if proposal.get("location") else {}),
            },
            "conflicts": conflicts,
        },
    }


def _local(value: str | None) -> str:
    """Local ISO without an offset, as the app sends for a proposal."""
    if not value:
        return "unknown"
    from datetime import datetime

    try:
        return timeutil.format_local(timeutil.to_utc_iso(datetime.fromisoformat(value)))
    except ValueError:
        return value


def _clock(value: str | None) -> str:
    if not value:
        return "?"
    from datetime import datetime

    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is not None:
        moment = timeutil.to_local(timeutil.to_utc_iso(moment))
    return moment.strftime("%-I:%M %p")


def _date_only(iso_with_offset: str) -> str:
    """'tomorrow', 'Friday', or 'Sat 19 Sep' -- never a clock time."""
    moment = timeutil.to_local(_utc(iso_with_offset))
    today = timeutil.start_of_local_day().date()
    delta = (moment.date() - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if 1 < delta < 7:
        return moment.strftime("%A")
    return moment.strftime("%a %-d %b")


def _utc(iso_with_offset: str) -> str:
    """The client sends local time with an offset; `timeutil` formats from UTC."""
    from datetime import datetime, timezone

    try:
        return datetime.fromisoformat(iso_with_offset).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return iso_with_offset
