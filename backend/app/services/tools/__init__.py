"""Structured tools the assistant can call.

Execution is deliberately separate from answer generation:

    selector.select()      one completion -> a tool name + arguments, or none
    registry.execute()     validate the arguments, run the handler
    ToolOutcome.to_text()  structured result as an indented note, placed in
                           the prompt's "Results for this message" section
    (answer generation)    the assistant writes the reply from that result

The assistant may only claim something happened when the result says
`"ok": true`. Gmail tools (`tools/gmail.py`) follow the exact same shape;
they simply call the Gmail API instead of SQLite, and are read-only --
including gmail.draft_reply, which only *retrieves* the email being
replied to. It never sends, saves, or creates anything; the reply text is
written by the normal answer-generation step below, from that retrieval.
"""

import sqlite3

from app.services.tools.base import Execution, ToolOutcome, ToolRegistry, ToolSpec, render_outcome
from app.services.tools.calendar import (
    CALENDAR_PROPOSE,
    CALENDAR_READ,
    calendar_tools,
    summarise,
)
from app.services.tools.gmail import (
    GMAIL_DRAFT_REPLY,
    GMAIL_READ,
    GMAIL_RECENT,
    GMAIL_SEARCH,
    gmail_tools,
)
from app.services.tools.selector import ToolCall, select
from app.services.tools.tasks import (
    TASKS_CANCEL,
    TASKS_COMPLETE,
    TASKS_COMPLETE_ITEM,
    TASKS_CREATE,
    TASKS_LIST,
    TASKS_OPEN_PANEL,
    TASKS_UPDATE,
    TaskTools,
)


def build_registry(db: sqlite3.Connection) -> ToolRegistry:
    """Every tool available for one request."""
    return ToolRegistry(TaskTools(db).specs() + calendar_tools() + gmail_tools())


__all__ = [
    "CALENDAR_PROPOSE",
    "CALENDAR_READ",
    "Execution",
    "GMAIL_DRAFT_REPLY",
    "GMAIL_READ",
    "GMAIL_RECENT",
    "GMAIL_SEARCH",
    "TASKS_CANCEL",
    "TASKS_COMPLETE",
    "TASKS_COMPLETE_ITEM",
    "TASKS_CREATE",
    "TASKS_LIST",
    "TASKS_OPEN_PANEL",
    "TASKS_UPDATE",
    "ToolCall",
    "ToolOutcome",
    "ToolRegistry",
    "ToolSpec",
    "build_registry",
    "calendar_tools",
    "gmail_tools",
    "render_outcome",
    "select",
    "summarise",
]
