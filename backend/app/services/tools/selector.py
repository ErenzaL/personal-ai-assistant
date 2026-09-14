"""Deciding which tool, if any, a message needs.

Separate from answer generation on purpose: this call only produces a tool
name and arguments, and it never writes anything the user sees. A cheap regex
screens first, so ordinary conversation costs nothing extra.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.services import timeutil
from app.services.llm import ChatMessage, LLMService
from app.services.tools.base import ToolRegistry

log = logging.getLogger("app.tools")

# Enough conversation for "move that one to Friday" to make sense.
CONTEXT_TURNS = 4

_TASK_WORDS = re.compile(
    r"\b(tasks?|to-?dos?|reminders?|remind|due|overdue|deadlines?|errands?)\b|할\s?일|해야|알림",
    re.IGNORECASE,
)
_ASKING = re.compile(
    r"\bwhat(?:'s| is| are)?\s+(?:on|due|left|pending)\b|\bwhat do i have\b|\bwhat should i do\b",
    re.IGNORECASE,
)
# Acting on an existing task is a strong signal on its own...
_STRONG_VERBS = re.compile(
    r"\b(mark|complete[d]?|finish\w*|cancel\w*|postpone|reschedul\w*)\b|\b(cross|tick) (it )?off\b",
    re.IGNORECASE,
)
# ...while these are common in ordinary speech, so they need a time word too.
_WEAK_VERBS = re.compile(r"\b(add|create|schedule|move|put)\b", re.IGNORECASE)
_TIME_WORDS = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|this (?:morning|afternoon|evening|week|weekend)|"
    r"next (?:week|month|mon|tues|wednes|thurs|fri|satur|sun)\w*|"
    r"mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d{1,2}\s?(?:am|pm)|\d{1,2}:\d{2})\b",
    re.IGNORECASE,
)
# A short reply picking from a list the assistant just offered: "2",
# "the second one", "the quarterly one".
# Anchored at both ends: the whole message must be the choice, so "no one
# knows" and "one sentence please" are not mistaken for a selection.
_CHOOSING = re.compile(
    r"^\s*(?:the\s+)?(?:(?:first|second|third|fourth|fifth|\d{1,2})(?:st|nd|rd|th)?(?:\s+one)?"
    r"|[\w'-]+\s+one)\s*[.!?]?\s*$",
    re.I,
)


def screen(text: str) -> bool:
    """Could this message need a task tool? A false positive costs one
    selection call and then falls through to normal chat; a false negative
    would break the feature, so this leans generous."""
    if _TASK_WORDS.search(text) or _ASKING.search(text) or _CHOOSING.match(text):
        return True
    if _STRONG_VERBS.search(text):
        return True
    return bool(_WEAK_VERBS.search(text) and _TIME_WORDS.search(text))


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


def _prompt(registry: ToolRegistry) -> str:
    return f"""\
You choose which tool, if any, answers the user's latest message. Reply with JSON only, no prose.

Right now it is {timeutil.describe_now()}.

Tools:
{registry.catalogue()}

Reply with {{"tool": "<name>", "arguments": {{...}}}} to call one, or {{"tool": null}} when the message
needs no tool (general questions, chit-chat, anything about a calendar event rather than a to-do).

Rules:
- Resolve every relative date against the current time above and write it in full as
  "YYYY-MM-DDTHH:MM:SS" local time. Bare days get a sensible hour: "tomorrow" -> 09:00,
  "this evening"/"tonight" -> 19:00, "this morning" -> 09:00, "this afternoon" -> 14:00.
- For tasks.create, the title is the action alone, without the date ("Buy groceries", "Call mom").
  If the user says "remind me ... at T", set both due_at and remind_at to T.
- For update, complete and cancel, put the distinctive words of the task in "match"
  ("phone bill", "quarterly report"). If an earlier message in this conversation listed
  candidates with a task_id and the user has now picked one, pass that task_id instead.
- Every argument is a single value, never an array.
"""


def parse_call(raw: str, registry: ToolRegistry) -> ToolCall | None:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        data = json.loads(body)
    except ValueError:
        log.info("tool selection: unparsable reply")
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("tool")
    if not isinstance(name, str) or name not in registry.names():
        return None
    arguments = data.get("arguments")
    return ToolCall(name, arguments if isinstance(arguments, dict) else {})


async def select(
    llm: LLMService,
    registry: ToolRegistry,
    message: str,
    history: list[ChatMessage] | None = None,
) -> ToolCall | None:
    """One completion that returns a tool call or nothing. Recent turns are
    included so follow-ups like "move that one to Friday" resolve."""
    messages = [ChatMessage("system", _prompt(registry))]
    messages.extend((history or [])[-CONTEXT_TURNS:])
    messages.append(ChatMessage("user", message))
    raw = await llm.generate(messages)
    call = parse_call(raw, registry)
    log.info("tool selection: %s", call.name if call else "none")
    return call
