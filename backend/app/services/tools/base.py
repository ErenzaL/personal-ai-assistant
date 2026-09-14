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

    @staticmethod
    def success(tool: str, **data: Any) -> "ToolOutcome":
        return ToolOutcome(True, tool, data=data)

    @staticmethod
    def failure(tool: str, code: str, message: str, **extra: Any) -> "ToolOutcome":
        return ToolOutcome(False, tool, error={"code": code, "message": message, **extra})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Any], ToolOutcome]

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
