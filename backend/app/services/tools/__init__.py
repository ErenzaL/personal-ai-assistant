"""Structured tools the assistant can call.

Execution is deliberately separate from answer generation:

    selector.select()      one completion -> a tool name + arguments, or none
    registry.execute()     validate the arguments, run the handler
    ToolOutcome.to_json()  structured result, placed in the prompt's
                           "Results for this message" section
    (answer generation)    the assistant writes the reply from that result

The assistant may only claim something happened when the result says
`"ok": true`.
"""

import sqlite3

from app.services.tools.base import ToolOutcome, ToolRegistry, ToolSpec
from app.services.tools.selector import ToolCall, screen, select
from app.services.tools.tasks import TaskTools


def build_registry(db: sqlite3.Connection) -> ToolRegistry:
    """Every tool available for one request."""
    return ToolRegistry(TaskTools(db).specs())


__all__ = [
    "ToolCall",
    "ToolOutcome",
    "ToolRegistry",
    "ToolSpec",
    "build_registry",
    "screen",
    "select",
]
