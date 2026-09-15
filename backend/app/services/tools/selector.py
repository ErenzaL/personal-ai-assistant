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
translation, and anything that does not ask about or change the user's own tasks, calendar, or email.
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
- gmail.recent is only for a plain "what's in my inbox" with no other criteria. The moment there
  is any criterion at all -- a date, a sender, a subject, read/unread, a topic -- use gmail.search
  instead, even for "today" or "recently": build a query rather than relying on the recency order.
- gmail.search's query is Gmail's own search syntax, not a sentence. Translate the request:
  a named sender/topic with no address -> plain words (from:professor is wrong if you were only
  told "my professor"; search professor instead, or the exact address/name if the user gave one,
  or if it is in "About the user" below); a date -> after:YYYY/MM/DD and/or before:YYYY/MM/DD
  (note: slashes, not dashes, unlike every other date in this prompt); "today" -> after: today's
  date; "unread" -> is:unread; a known sender's address or domain -> from:; a subject phrase ->
  subject:"...". Never invent a specific email address that was not given to you.
- Combining terms with spaces is an AND in Gmail search, which narrows results -- every extra word
  must actually be likely to appear, literally, in the email. A topic word you are paraphrasing
  ("order", "meeting") often will not: the email may be in another language, or word it completely
  differently. When you already have a strong, specific term (a sender's name/domain, an exact
  subject phrase given by the user), prefer that alone over ANDing in a guessed topic word that
  could cause a real, findable email to be missed entirely. "Find the email about my order from
  Coupang" -> from:coupang alone is safer than from:coupang order.
- gmail.read is for when the user wants to know what an email actually *says*, not just whether
  or when it arrived ("read me the email about X", "what did they say", "summarize the email
  from X"). Give query (a short description of which email), not message_id, unless an id from
  earlier in this exact reply is available. "Summarize my unread emails" (plural, general) is
  gmail.search with query is:unread -- summarizing many emails from their subjects and previews
  is answer generation, not a reason to read each one in full.
- gmail.draft_reply is for "reply to X", "help me answer X", "draft a response to X" -- the user
  wants a reply written, not just the email described. Build query the same way as gmail.read: if
  the conversation already identified an email (you or the user named its sender/subject earlier
  in this reply), reconstruct query from that; if there is truly nothing to go on ("reply to this
  email" out of nowhere), leave query empty and it defaults to the latest inbox email. Do not use
  gmail.draft_reply again just to change a draft already shown earlier in this conversation --
  "make it shorter", "more formal", "add that I'm free Friday" are edits to your own previous
  reply and need no tool at all, the same as revising anything else you already wrote.
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
