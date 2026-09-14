"""Deciding which tool, if any, a message needs.

Separate from answer generation on purpose: this call only produces a tool
name and arguments, and it never writes anything the user sees. Every message
goes through it: there is no keyword rule in front, so the model itself judges
whether the user is asking about their tasks or calendar, however they phrase
it. The price is one extra short completion per message.
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
needs no tool. Most messages need none: greetings, thanks, general knowledge, explanations, writing,
translation, and anything that does not ask about or change the user's own tasks or calendar.
Judge the intent from the wording, in any language and however casual it is: "what i have this
week?", "anything tomorrow?", "이번 주에 뭐 있어?" all ask about the calendar.

Rules:
- Resolve every relative date against the current time above and write it in full as
  "YYYY-MM-DDTHH:MM:SS" local time. Bare days get a sensible hour: "tomorrow" -> 09:00,
  "this evening"/"tonight" -> 19:00, "this morning" -> 09:00, "this afternoon" -> 14:00.
- For tasks.create, the title is the action alone, without the date ("Buy groceries", "Call mom").
  If the user says "remind me ... at T", set both due_at and remind_at to T.
- For calendar.read, resolve the period the user means into explicit local start/end bounds:
  a day is 00:00:00 to the next day 00:00:00; "this afternoon" is 12:00:00-18:00:00;
  "this evening" 18:00:00-23:59:59; a weekend is Saturday 00:00:00 to Monday 00:00:00;
  "next appointment" is from now to 30 days ahead. Use it for questions about what is on,
  whether the user is free, or when something happens -- never for to-do items.
- calendar.propose_event is for putting something ON the calendar at a time ("add gym tomorrow
  at 7pm", "schedule dinner Friday at 6", "put dentist on Monday at 2"). Give the title without
  the date ("Gym", "Dinner with Mina"). Set duration_minutes only when the user states a length;
  leave it out otherwise. Pass calendar_name only if they name one ("my personal calendar").
  A to-do with no time is tasks.create, not a calendar event.
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
