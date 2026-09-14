"""Structured tools the assistant can call.

Execution is deliberately separate from answer generation:

    selector.select()      one completion -> a tool name + arguments, or none
    registry.execute()     validate the arguments, run the handler
    ToolOutcome.to_text()  structured result as an indented note, placed in
                           the prompt's "Results for this message" section
    (answer generation)    the assistant writes the reply from that result

The assistant may only claim something happened when the result says
`"ok": true`.
"""

import sqlite3

from app.services.tools.base import Execution, ToolOutcome, ToolRegistry, ToolSpec, render_outcome
from app.services.tools.calendar import (
    CALENDAR_PROPOSE,
    CALENDAR_READ,
    calendar_tools,
    summarise,
)
from app.services.tools.selector import ToolCall, select
from app.services.tools.tasks import TaskTools


def build_registry(db: sqlite3.Connection) -> ToolRegistry:
    """Every tool available for one request."""
    return ToolRegistry(TaskTools(db).specs() + calendar_tools())


__all__ = [
    "CALENDAR_PROPOSE",
    "CALENDAR_READ",
    "Execution",
    "ToolCall",
    "ToolOutcome",
    "ToolRegistry",
    "ToolSpec",
    "build_registry",
    "calendar_tools",
    "render_outcome",
    "select",
    "summarise",
]
