"""Local time in, UTC on disk.

Every timestamp in the database is ISO 8601 UTC, so rows sort and compare as
plain strings. Everything the user sees or says is in their machine's local
timezone. These helpers are the only place the two meet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

ISO_SECONDS = "seconds"

# Guard rails for anything a model or a user hands us.
MIN_YEAR = 2000
MAX_YEAR = 2100


class TimeError(ValueError):
    """Message is safe to show to the user."""


def local_tz() -> tzinfo:
    """The machine's current local timezone, including the right DST offset."""
    return datetime.now().astimezone().tzinfo or timezone.utc


def now_local() -> datetime:
    return datetime.now(local_tz())


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec=ISO_SECONDS)


def to_utc_iso(moment: datetime) -> str:
    """Aware or naive datetime -> UTC ISO string. Naive means local time."""
    aware = moment if moment.tzinfo else moment.replace(tzinfo=local_tz())
    return aware.astimezone(timezone.utc).isoformat(timespec=ISO_SECONDS)


def parse_to_utc_iso(value: str, *, label: str = "date") -> str:
    """Parse what the interpreter produced (usually naive local ISO) and
    return a UTC ISO string. Raises TimeError with a readable message."""
    text = value.strip()
    if not text:
        raise TimeError(f"The {label} was empty.")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as err:
        raise TimeError(f"I couldn't read that {label}.") from err
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise TimeError(f"That {label} doesn't look right ({parsed.year}).")
    return to_utc_iso(parsed)


def to_local(utc_iso: str) -> datetime:
    parsed = datetime.fromisoformat(utc_iso)
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(local_tz())


def start_of_local_day(offset_days: int = 0) -> datetime:
    base = now_local() + timedelta(days=offset_days)
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def local_day_range(offset_days: int = 0) -> tuple[str, str]:
    """[start, end) of a local day, as UTC ISO strings."""
    start = start_of_local_day(offset_days)
    return to_utc_iso(start), to_utc_iso(start + timedelta(days=1))


def local_week_range(days: int = 7) -> tuple[str, str]:
    """[today 00:00, +days) in local time, as UTC ISO strings."""
    start = start_of_local_day()
    return to_utc_iso(start), to_utc_iso(start + timedelta(days=days))


def format_local(utc_iso: str | None) -> str:
    """Short, human phrasing of a stored timestamp: 'today at 6:00 PM',
    'tomorrow at 9:00 AM', 'Fri 19 Sep at 6:00 PM'."""
    if not utc_iso:
        return "no date"
    moment = to_local(utc_iso)
    today = start_of_local_day().date()
    delta = (moment.date() - today).days
    clock = moment.strftime("%-I:%M %p")
    if delta == 0:
        return f"today at {clock}"
    if delta == 1:
        return f"tomorrow at {clock}"
    if delta == -1:
        return f"yesterday at {clock}"
    if 1 < delta < 7:
        return f"{moment.strftime('%A')} at {clock}"
    return f"{moment.strftime('%a %-d %b')} at {clock}"


def describe_now() -> str:
    """Current local date and time, for the interpreter prompt."""
    now = now_local()
    return f"{now.strftime('%A %d %B %Y, %H:%M')} (local time, UTC{now.strftime('%z')})"
