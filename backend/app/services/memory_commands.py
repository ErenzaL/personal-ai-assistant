"""Explicit memory commands spoken in normal chat: recall / forget.

Creating a memory is no longer handled here: `memory_extraction.py` runs on
every user message and picks up anything worth keeping, explicitly asked for
or not, with a merge step that avoids duplicates. What is left here are the
two things that are genuinely *commands* rather than passive learning --
asking what is stored, and asking to remove something -- for which a
deliberate, deterministic action still makes sense:

    screen()      cheap regex: could this be a recall/forget request?
    interpret()   one LLM call returning strict JSON (intent + fields)
    execute()     deterministic: MemoryService does the work, and the reply
                  text is composed here from the *actual* database outcome

The model only interprets language. It never writes the confirmation, so it
cannot claim something was forgotten unless the database did it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from app.database.models import MEMORY_CATEGORIES, Memory
from app.database.repositories import SettingsRepository
from app.services.llm import ChatMessage, LLMService
from app.services.memory import MemoryService

Intent = Literal["recall", "forget", "none"]

# --- Stage 1: screen -------------------------------------------------------------

# "remember" is deliberately absent: a bare "remember that X" is now just an
# ordinary message, caught the same way any other stated fact is -- by the
# passive extraction pipeline that runs on every turn (memory_extraction.py).
# This regex only has to catch the two things that still need a *command*:
# asking what is known, and asking to remove something.
_SCREEN = re.compile(
    r"\b(recall|forget|forgot|what do you know about me|about me)\b|기억|잊어|잊지",
    re.IGNORECASE,
)
# A bare number / ordinal is only meaningful while a forget-choice is pending.
_CHOICE = re.compile(r"^\s*(?:#|number\s*|the\s+)?(\d{1,2}|first|second|third|fourth|fifth)(?:st|nd|rd|th)?(?:\s+one)?\s*[.!]?\s*$", re.I)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}

# Backstop for sensitive facts, independent of the model's judgement.
_SENSITIVE = re.compile(
    r"\b(password|passcode|pin code|\bpin\b|ssn|social security|passport number|credit card|card number|"
    r"bank account|routing number|diagnos|prescription|medication|hiv|pregnan|therapist|religio|"
    r"sexual|political party|immigration status|visa status)\b",
    re.IGNORECASE,
)

PENDING_FORGET_KEY = "pending_forget"  # settings row: {"conversation_id", "ids"}

_CATEGORY_LABEL = {
    "profile": "About you",
    "preference": "Preferences",
    "routine": "Routines",
    "goal": "Goals",
    "project": "Projects",
    "person": "People",
    "important_fact": "Important facts",
}

_STOPWORDS = {
    "the", "a", "an", "my", "me", "i", "that", "this", "it", "to", "of", "about", "and", "or", "in", "on",
    "for", "with", "is", "are", "was", "be", "do", "you", "your", "please", "remember", "forget", "recall",
    "memory", "memories", "saved", "thing", "one", "preference", "preferences", "fact", "facts",
}


def screen(text: str) -> bool:
    return bool(_SCREEN.search(text))


def is_choice(text: str) -> int | None:
    """Parse a reply like '2', 'the second one' into a 1-based index."""
    m = _CHOICE.match(text)
    if not m:
        return None
    token = m.group(1).lower()
    return int(token) if token.isdigit() else _ORDINALS[token]


# --- Stage 2: interpret (LLM -> JSON) ---------------------------------------------

_INTERPRET_PROMPT = f"""\
You classify ONE user message for a personal-memory feature of an assistant. Reply with JSON only, no prose.

Schema:
{{"intent": "recall" | "forget" | "none",
 "category": one of {list(MEMORY_CATEGORIES)} or null,
 "keywords": [2-5 distinctive words]}}

Rules:
- "recall": the user asks what you remember / know about them, optionally one area. Set category if they \
name one (preferences -> preference, projects -> project, people -> person, routines -> routine, \
goals -> goal, profile/basic info -> profile, important facts -> important_fact), else null.
- "forget": the user asks to forget / remove / delete a saved fact. Set keywords (distinctive words that \
would appear in the saved fact, e.g. ["appointments", "2 PM"]) and category if they name one.
- "none": anything else. Saving a new fact is not handled here -- that happens automatically from \
ordinary conversation elsewhere -- so a plain statement like "remember that I like tea" is also "none";
this classifier only ever fires on an explicit request to *see* or *delete* what is already stored.
"""


@dataclass(frozen=True)
class MemoryIntent:
    intent: Intent
    category: str | None = None
    keywords: list[str] = field(default_factory=list)


async def interpret(llm: LLMService, text: str) -> MemoryIntent:
    """Ask the model to classify; any parse problem degrades to 'none'."""
    raw = await llm.generate([ChatMessage("system", _INTERPRET_PROMPT), ChatMessage("user", text)])
    return parse_intent(raw)


def parse_intent(raw: str) -> MemoryIntent:
    body = raw.strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body, flags=re.I)
    try:
        data = json.loads(body)
    except ValueError:
        return MemoryIntent("none")
    if not isinstance(data, dict):
        return MemoryIntent("none")
    intent = data.get("intent")
    if intent not in ("recall", "forget"):
        return MemoryIntent("none")
    category = data.get("category")
    return MemoryIntent(
        intent=intent,
        category=category if category in MEMORY_CATEGORIES else None,
        keywords=[k for k in data.get("keywords") or [] if isinstance(k, str) and k.strip()],
    )


# --- Stage 3: execute (deterministic) ----------------------------------------------


class MemoryCommandHandler:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._memory = MemoryService(db)
        self._settings = SettingsRepository(db)

    # -- pending forget choice --

    def pending_choice(self, conversation_id: str, text: str) -> str | None:
        """If a forget-choice is pending in this conversation and `text` picks
        one, resolve it and return the reply. Otherwise None (and any stale
        pending choice is cleared when the user says something else)."""
        pending = self._settings.get(PENDING_FORGET_KEY)
        if not pending or pending.get("conversation_id") != conversation_id:
            return None
        index = is_choice(text)
        ids: list[str] = pending.get("ids", [])
        if index is None:
            self._settings.delete(PENDING_FORGET_KEY)
            return None
        if not 1 <= index <= len(ids):
            return f"Please reply with a number between 1 and {len(ids)}, or tell me what to forget."
        self._settings.delete(PENDING_FORGET_KEY)
        record = self._memory.deactivate_memory(ids[index - 1])
        return f"Done, I've forgotten that: {record.content}"

    # -- dispatch --

    def execute(self, intent: MemoryIntent, original_text: str, conversation_id: str) -> str:
        self._settings.delete(PENDING_FORGET_KEY)
        if intent.intent == "recall":
            return self._recall(intent)
        return self._forget(intent, original_text, conversation_id)

    # -- recall --

    def _recall(self, intent: MemoryIntent) -> str:
        items = self._memory.list_memories(category=intent.category)
        if not items:
            if intent.category:
                label = _CATEGORY_LABEL[intent.category].lower()
                return f"I don't have anything saved under {label} yet. Tell me with \"Remember that …\" and I'll keep it."
            return "I don't have anything saved about you yet. Tell me things to keep with \"Remember that …\"."
        if intent.category:
            lines = [f"Here's what I remember about your {_CATEGORY_LABEL[intent.category].lower()}:"]
            lines += [f"- {m.content}" for m in items]
            return "\n".join(lines)
        lines = ["Here's what I remember about you:"]
        for category in MEMORY_CATEGORIES:
            group = [m for m in items if m.category == category]
            if group:
                lines.append(f"\n**{_CATEGORY_LABEL[category]}**")
                lines += [f"- {m.content}" for m in group]
        return "\n".join(lines)

    # -- forget --

    def _forget(self, intent: MemoryIntent, original_text: str, conversation_id: str) -> str:
        candidates = self._candidates(intent, original_text)
        if not candidates:
            return "I couldn't find a saved memory matching that. Ask \"What do you remember about me?\" to see what's saved."
        if len(candidates) == 1 or _clear_winner(candidates):
            record = self._memory.deactivate_memory(candidates[0][0].id)
            return f"Done, I've forgotten that: {record.content}"
        shown = candidates[:5]
        self._settings.set(PENDING_FORGET_KEY, {"conversation_id": conversation_id, "ids": [m.id for m, _ in shown]})
        lines = [f"I found {len(shown)} matching memories. Which one should I forget?"]
        lines += [f"{i}. {m.content}" for i, (m, _) in enumerate(shown, 1)]
        lines.append("Reply with the number.")
        return "\n".join(lines)

    def _candidates(self, intent: MemoryIntent, original_text: str) -> list[tuple[Memory, int]]:
        """Active memories scored by how many keywords they contain, best first."""
        terms = _terms(intent.keywords) or _terms(_strip_command(original_text).split())
        pool = self._memory.list_memories(category=intent.category)
        scored = []
        for m in pool:
            hay = f"{m.key.replace('_', ' ')} {m.content}".lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((m, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].updated_at))
        return scored


# --- helpers ----------------------------------------------------------------------


def _clear_winner(candidates: list[tuple[Memory, int]]) -> bool:
    best, second = candidates[0][1], candidates[1][1]
    return best >= 2 and best > second


def _terms(words: list[str]) -> list[str]:
    out = []
    for w in words:
        for piece in re.split(r"[^\w]+", w.lower()):
            if len(piece) >= 2 and piece not in _STOPWORDS:
                out.append(piece)
    return list(dict.fromkeys(out))


def _strip_command(text: str) -> str:
    """'Remember that I prefer X' -> 'I prefer X' (fallback when the model gave no content)."""
    cleaned = re.sub(r"^\s*(please\s+)?(remember|forget|recall)\s+(that\s+|the\s+|my\s+)?", "", text, flags=re.I)
    return cleaned.strip().rstrip(".")

def _strip_sensitive(text: str) -> str:
    """Remove any sensitive keywords from the text to avoid accidental exposure."""
    return _SENSITIVE.sub("[REDACTED]", text)

