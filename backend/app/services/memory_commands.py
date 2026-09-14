"""Explicit memory commands spoken in normal chat: remember / recall / forget.

Flow for one user message (see `api/chat.py`):

    screen()      cheap regex: could this be a memory command?  -> no: normal chat
    interpret()   one LLM call returning strict JSON (intent + structured fields)
    execute()     deterministic: MemoryService does the work, and the reply text
                  is composed here from the *actual* database outcome

The model only interprets language. It never writes the confirmation, so it
cannot claim something was saved or forgotten unless the database did it.
Nothing is stored unless the user explicitly asked.
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
from app.services.memory import InvalidMemory, MemoryConflict, MemoryService, slug_key

Intent = Literal["remember", "recall", "forget", "none"]

# --- Stage 1: screen -------------------------------------------------------------

_SCREEN = re.compile(
    r"\b(remember|recall|forget|forgot|memori[sz]e|keep in mind|what do you know about me|about me)\b|기억|잊어|잊지",
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
{{"intent": "remember" | "recall" | "forget" | "none",
 "category": one of {list(MEMORY_CATEGORIES)} or null,
 "key": short lower_snake_case identifier or null,
 "content": short third-person fact or null,
 "keywords": [2-5 distinctive words] ,
 "sensitive": true | false}}

Rules:
- "remember": the user explicitly asks to remember / save / keep in mind a durable fact about themselves, \
their life, work, preferences, routines, goals, projects, or people they know. Fill category, key, content. \
content = the fact rewritten as a short statement about the user in third person, keeping specifics \
(e.g. "Prefers meetings after 2 PM", "Current main project is Ellen AI"); start with the verb or noun, \
not with "User". key = stable identifier for that \
fact (e.g. preferred_meeting_time, reminder_lead_time, current_project).
- "recall": the user asks what you remember / know about them, optionally one area. Set category if they \
name one (preferences -> preference, projects -> project, people -> person, routines -> routine, \
goals -> goal, profile/basic info -> profile, important facts -> important_fact), else null.
- "forget": the user asks to forget / remove / delete a saved fact. Set keywords (distinctive words that \
would appear in the saved fact, e.g. ["appointments", "2 PM"]) and category if they name one.
- "none": anything else, including "I can't remember the name of that movie", questions about memory in \
general, requests to remember something for someone else, and one-off things to do ("remember to buy \
milk tomorrow", "remind me to call the bank") -- those are tasks, not durable facts.
- sensitive = true if the fact reveals health or medical details, religion, sexual orientation, political \
views, immigration status, ethnicity, passwords/PINs/account numbers, or an exact home address.
"""


@dataclass(frozen=True)
class MemoryIntent:
    intent: Intent
    category: str | None = None
    key: str | None = None
    content: str | None = None
    keywords: list[str] = field(default_factory=list)
    sensitive: bool = False


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
    if intent not in ("remember", "recall", "forget"):
        return MemoryIntent("none")
    category = data.get("category")
    return MemoryIntent(
        intent=intent,
        category=category if category in MEMORY_CATEGORIES else None,
        key=data.get("key") if isinstance(data.get("key"), str) else None,
        content=data.get("content") if isinstance(data.get("content"), str) else None,
        keywords=[k for k in data.get("keywords") or [] if isinstance(k, str) and k.strip()],
        sensitive=bool(data.get("sensitive")),
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
        if intent.intent == "remember":
            return self._remember(intent, original_text)
        if intent.intent == "recall":
            return self._recall(intent)
        return self._forget(intent, original_text, conversation_id)

    # -- remember --

    def _remember(self, intent: MemoryIntent, original_text: str) -> str:
        content = _normalise_fact((intent.content or "").strip() or _strip_command(original_text))
        if intent.sensitive or _SENSITIVE.search(content) or _SENSITIVE.search(original_text):
            return "That sounds like sensitive personal information, so I won't store it."
        category = intent.category or "important_fact"
        key = _usable_key(intent.key) or _slug_key(content)
        try:
            record = self._memory.create_memory(category, key, content, source="user", confidence=1.0)
        except MemoryConflict:
            existing = self._memory.search_memories(key=key, category=category, include_inactive=True)
            if not existing:
                return "I couldn't save that. Please try rephrasing it."
            old = existing[0]
            if not old.is_active:
                self._memory.reactivate_memory(old.id)
            if old.content.strip().lower() == content.strip().lower():
                return f"I already have that saved: {old.content}"
            record = self._memory.update_memory(old.id, content=content, source="user", confidence=1.0)
            return f"Updated what I remember: {record.content} (it was: {old.content})"
        except InvalidMemory as err:
            return f"I couldn't save that: {err.message}"
        return f"I'll remember that: {record.content}"

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


def _normalise_fact(content: str) -> str:
    """'User prefers X.' -> 'Prefers X' so replies read naturally."""
    text = re.sub(r"^(the\s+)?user('s)?\s+", "", content.strip(), flags=re.I).strip().rstrip(".")
    return text[:1].upper() + text[1:] if text else content.strip()


def _usable_key(key: str | None) -> str | None:
    if not key:
        return None
    candidate = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return candidate[:64] or None


def _slug_key(content: str) -> str:
    return slug_key(content)
