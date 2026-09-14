"""Tool plumbing: typed arguments, validation, structured results.

A tool is a name, a description, a Pydantic model for its arguments, and a
handler. Arguments are always validated before the handler runs, so a handler
never sees a malformed value, and every call returns the same JSON envelope:

    {"ok": true,  "tool": "...", "data": {...}}
    {"ok": false, "tool": "...", "error": {"code": "...", "message": "...", ...}}

`ToolOutcome.ok` is what the assistant must look at before claiming anything
happened. The registry also derives each tool's signature from its argument
model, so the text shown to the model and the validation can never drift.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

log = logging.getLogger("app.tools")


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        body: dict[str, Any] = {"ok": self.ok, "tool": self.tool}
        if self.ok:
            body["data"] = self.data
        else:
            body["error"] = self.error
        return json.dumps(body, ensure_ascii=False, indent=None)

    def to_text(self) -> str:
        """The outcome as an indented note, for the prompt. Plain text on
        purpose: presented as JSON, Gemini 3.5 mistakes a tool result for one
        of its own function calls and echoes it instead of answering."""
        body = {"ok": self.ok, "data" if self.ok else "error": self.data if self.ok else self.error}
        return render_text(body)

    @staticmethod
    def success(tool: str, **data: Any) -> "ToolOutcome":
        return ToolOutcome(True, tool, data=data)

    @staticmethod
    def failure(tool: str, code: str, message: str, **extra: Any) -> "ToolOutcome":
        return ToolOutcome(False, tool, error={"code": code, "message": message, **extra})


def render_text(value: Any, indent: int = 0) -> str:
    """Nested dicts and lists as indented `key: value` lines, YAML-like but
    without quoting rules. Empty containers render as `(none)` so an empty
    result is visibly empty rather than missing."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return f"{pad}(none)"
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.append(render_text(item, indent + 1))
            else:
                lines.append(f"{pad}{key}: {_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{pad}(none)"
        lines = []
        for item in value:
            if isinstance(item, dict) and item:
                nested = render_text(item, indent + 1).splitlines()
                first = nested[0].strip()
                lines.append(f"{pad}- {first}")
                lines.extend(nested[1:])
            else:
                lines.append(f"{pad}- {_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_scalar(value)}"


def _scalar(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return "(none)"
    return str(value)


def render_outcome(body: dict[str, Any]) -> str:
    """A client-side outcome (same envelope) as the same kind of note."""
    return render_text({k: v for k, v in body.items() if k != "tool"})


class Execution(Enum):
    """Where a tool runs. Calendar access lives in the native layer, so those
    tools are dispatched to the desktop client and their result is posted
    back; everything else runs here."""

    LOCAL = "local"
    CLIENT = "client"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Any], ToolOutcome] | None = None
    execution: Execution = Execution.LOCAL

    @property
    def runs_on_client(self) -> bool:
        return self.execution is Execution.CLIENT

    def signature(self) -> str:
        """Compact call signature derived from the argument model."""
        schema = self.args_model.model_json_schema()
        required = set(schema.get("required", []))
        parts = []
        for field_name, spec in schema.get("properties", {}).items():
            mark = "" if field_name in required else "?"
            parts.append(f"{field_name}{mark}: {_type_text(spec, schema)}")
        return f"{self.name}({', '.join(parts)})"


def _type_text(spec: dict[str, Any], root: dict[str, Any]) -> str:
    """Human-readable type for one property, following $ref and enums."""
    if "$ref" in spec:
        name = spec["$ref"].rsplit("/", 1)[-1]
        spec = root.get("$defs", {}).get(name, {})
    if "enum" in spec:
        return "|".join(json.dumps(v) for v in spec["enum"])
    if "anyOf" in spec:
        options = [_type_text(o, root) for o in spec["anyOf"] if o.get("type") != "null"]
        return "|".join(dict.fromkeys(options)) or "string"
    if spec.get("type") == "array":
        return f"{_type_text(spec.get('items', {}), root)}[]"
    return {"integer": "int", "number": "number", "boolean": "bool"}.get(spec.get("type", "string"), "string")


class ToolRegistry:
    """The tools one request may use. Built per request, over one connection."""

    def __init__(self, tools: list[ToolSpec]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def runs_on_client(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool is not None and tool.runs_on_client

    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | ToolOutcome:
        """Check arguments without running anything. Used before handing a
        client-side tool to the desktop app, so bad model output is caught
        here rather than there."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome.failure(name, "unknown_tool", f"There is no tool called {name}.")
        try:
            return tool.args_model.model_validate(arguments or {}).model_dump()
        except ValidationError as err:
            fields = sorted({str(e["loc"][0]) for e in err.errors() if e.get("loc")})
            log.info("tool %s: invalid arguments (%s)", name, ", ".join(fields) or "unknown")
            return ToolOutcome.failure(
                name, "invalid_arguments", "Those arguments are not valid for this tool.", fields=fields
            )

    def catalogue(self) -> str:
        """Signatures and descriptions, for the selection prompt."""
        return "\n".join(f"- {t.signature()}\n    {t.description}" for t in self._tools.values())

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Validate then run. Never raises: failures come back as outcomes.

        Logs the tool name, whether it succeeded, and how long it took.
        Arguments and task content are deliberately not logged.
        """
        tool = self._tools.get(name)
        if tool is None:
            log.warning("tool %s: unknown", name)
            return ToolOutcome.failure(name, "unknown_tool", f"There is no tool called {name}.")
        if tool.handler is None:
            log.warning("tool %s: has no server-side handler", name)
            return ToolOutcome.failure(name, "tool_failed", "That tool cannot run here.")

        try:
            args = tool.args_model.model_validate(arguments or {})
        except ValidationError as err:
            fields = sorted({str(e["loc"][0]) for e in err.errors() if e.get("loc")})
            log.info("tool %s: invalid arguments (%s)", name, ", ".join(fields) or "unknown")
            return ToolOutcome.failure(
                name,
                "invalid_arguments",
                "Those arguments are not valid for this tool.",
                fields=fields,
            )

        started = time.perf_counter()
        try:
            outcome = tool.handler(args)
        except Exception:  # a bug in a handler must not take the reply down
            log.exception("tool %s: handler raised", name)
            outcome = ToolOutcome.failure(name, "tool_failed", "That didn't work. Please try again.")
        elapsed_ms = round((time.perf_counter() - started) * 1000)

        log.info(
            "tool %s: %s in %dms%s",
            name,
            "ok" if outcome.ok else "failed",
            elapsed_ms,
            "" if outcome.ok else f" ({outcome.error.get('code')})",
        )
        return outcome
