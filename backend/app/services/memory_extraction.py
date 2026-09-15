"""Deciding what to remember from ordinary conversation.

Runs after every user message (concurrently with generating the reply, so it
never adds visible latency -- see `api/chat.py`). One LLM call does the whole
job: given the message, a little context, and any existing memories that are
semantically close to it, the model decides whether there is a durable fact
worth keeping and, if so, whether it is new or an update to something already
stored. That merge decision is what lets "I want to focus on data science
now" recognise it should replace "interested in becoming a data analyst"
instead of creating a second, conflicting memory.

    candidates()   embed the message, rank existing memories by similarity
                   (reuses the same query embedding retrieval already needs)
    decide()       one LLM call: create / update / ignore, as strict JSON
    apply()        deterministic: writes through MemoryService, embeds the
                   final content, never claims a save the database refused

The model only decides *what* the fact is and *whether* it matters; whether
anything was actually written is always read back from the database, the
same discipline the rest of this app's tool-calling already follows.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass

from app.database.models import MEMORY_CATEGORIES, Memory
from app.services.embeddings import cosine_similarity
from app.services.llm import ChatMessage, LLMService
from app.services.memory import MemoryConflict, MemoryError, MemoryService

log = logging.getLogger("app.memory")

# How many existing memories to offer the model as possible merge targets.
# Small on purpose: this is a prompt, not a database dump, and the semantic
# ranking already puts the true candidate first almost always (see
# retrieval.py's module docstring for the calibration this is based on).
CANDIDATE_COUNT = 5
# Same floor as retrieval.py, for the same reason: below this a similarity
# score is noise, not a real "maybe related" signal.
SIMILARITY_FLOOR = 0.35
# A handful of recent turns for pronoun/context resolution ("That's actually
# my brother" needs to know who was just mentioned), not the whole history.
CONTEXT_TURNS = 4

# Independent backstop, same policy the old explicit-remember command
# enforced: never store this even if the model says to. A prompt instruction
# asks for the same thing; this is what actually blocks it.
_SENSITIVE = re.compile(
    r"\b(password|passcode|pin code|\bpin\b|ssn|social security|passport number|credit card|card number|"
    r"bank account|routing number|diagnos|prescription|medication|hiv|pregnan|therapist|religio|"
    r"sexual|political party|immigration status|visa status)\b",
    re.IGNORECASE,
)

_PROMPT = f"""\
You quietly decide whether the user's latest message reveals a durable fact worth remembering \
long-term, for a personal assistant. Most messages reveal nothing worth keeping. Reply with JSON \
only, no prose.

Schema:
{{"action": "create" | "update" | "ignore",
 "memory_id": "<id from the candidates below, required only when action is update>",
 "category": one of {list(MEMORY_CATEGORIES)},
 "key": short lower_snake_case identifier,
 "content": the fact, rewritten as a short third-person statement (e.g. "Prefers to be called Ellen",
   "Current career interest is data science and AI"),
 "importance": 0.0-1.0, how much this matters if true (a name or a standing preference is high;
   a passing mention of the weather is low),
 "confidence": 0.0-1.0, how sure you are this is actually true and durable (not a joke, not
   hypothetical, not about someone else)}}

Rules:
- "ignore" is the right answer for: small talk, questions, task/calendar requests, opinions about
  third parties, anything hypothetical or uncertain ("maybe I'll try..."), and anything that is
  already captured by an existing memory with no real change.
- "create" is for a genuinely new durable fact -- about the user's identity, preferences, routines,
  goals, projects, or people in their life -- that does not meaningfully overlap any candidate below.
- "update" is for a message that changes, refines, or supersedes one of the candidate memories listed
  below (a change of mind, a correction, new specifics). Set memory_id to that candidate's id and
  content to the fact as it now stands -- write the *new* truth, not a merge of the old wording and
  the new. A career interest changing from data analysis to data science and AI is an update to that
  same career memory, not a new one.
- Never extract or store: passwords, PINs, account or card numbers, exact health/medical details,
  religion, sexual orientation, immigration status, or an exact home address. If the message contains
  one of these, the answer is "ignore" regardless of anything else in it.
- Only extract what the user says about *themselves*, never what they report about someone else,
  unless the fact itself is explicitly about their relationship to that person (e.g. "my brother's
  name is Tom" is a "person" fact about the user's own life).
"""


@dataclass(frozen=True)
class ExtractionResult:
    """What happened, for the caller to show "Remembered: ..." feedback --
    only when something genuinely new was written, never on ignore."""

    saved: bool
    content: str | None = None


@dataclass(frozen=True)
class _Decision:
    action: str
    memory_id: str | None
    category: str | None
    key: str | None
    content: str | None
    importance: float
    confidence: float


def _parse(raw: str) -> _Decision | None:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    if action not in ("create", "update", "ignore"):
        return None

    def _clamp01(value: object, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    return _Decision(
        action=action,
        memory_id=data.get("memory_id") if isinstance(data.get("memory_id"), str) else None,
        category=data.get("category") if data.get("category") in MEMORY_CATEGORIES else None,
        key=data.get("key") if isinstance(data.get("key"), str) else None,
        content=data.get("content") if isinstance(data.get("content"), str) else None,
        importance=_clamp01(data.get("importance"), 0.5),
        confidence=_clamp01(data.get("confidence"), 0.7),
    )


async def _candidates(
    memory: MemoryService, llm: LLMService, message: str
) -> tuple[list[float] | None, list[Memory]]:
    """The message's own embedding (reusable by the caller) and the existing
    memories most likely to be the same underlying fact, best first."""
    pool = memory.list_with_embeddings()
    if not pool:
        return None, []
    vector = await llm.embed(message, task="query")
    if vector is None:
        return None, []
    scored = [(cosine_similarity(vector, m.embedding), m) for m in pool if m.embedding]
    scored = [pair for pair in scored if pair[0] >= SIMILARITY_FLOOR]
    scored.sort(key=lambda pair: -pair[0])
    return vector, [m for _, m in scored[:CANDIDATE_COUNT]]


def _render_candidates(candidates: list[Memory]) -> str:
    if not candidates:
        return "(none)"
    return "\n".join(f'- id={m.id} category={m.category}: "{m.content}"' for m in candidates)


async def extract(
    llm: LLMService,
    memory: MemoryService,
    message: str,
    history: list[ChatMessage],
    conversation_id: str,
) -> ExtractionResult:
    """Decide, and act on the decision. Never raises: a bad response, a
    network failure, or a storage error all just mean nothing was saved this
    turn -- the feature degrading is fine, breaking the chat reply is not."""
    if _SENSITIVE.search(message):
        log.info("memory extraction: skipped (sensitive content)")
        return ExtractionResult(saved=False)

    try:
        vector, candidates = await _candidates(memory, llm, message)
        prompt = [
            ChatMessage("system", _PROMPT + f"\nCandidate existing memories:\n{_render_candidates(candidates)}"),
            *history[-CONTEXT_TURNS:],
            ChatMessage("user", message),
        ]
        raw = await llm.generate(prompt)
    except Exception:
        log.warning("memory extraction: model call failed", exc_info=True)
        return ExtractionResult(saved=False)

    decision = _parse(raw)
    if decision is None or decision.action == "ignore":
        log.info("memory extraction: %s", "ignore" if decision else "unparsable, treated as ignore")
        return ExtractionResult(saved=False)
    if not decision.content or _SENSITIVE.search(decision.content):
        log.info("memory extraction: dropped (empty or sensitive content)")
        return ExtractionResult(saved=False)

    # The final embedding is of the *decided* content, not the raw message:
    # future retrieval compares against this text, so it should describe
    # what is actually stored.
    if vector is not None and decision.action == "update" and decision.memory_id:
        matched = next((m for m in candidates if m.id == decision.memory_id), None)
        embedding = await llm.embed(decision.content, task="document") if matched else None
    else:
        embedding = await llm.embed(decision.content, task="document")

    try:
        if decision.action == "update" and decision.memory_id:
            existing = next((m for m in candidates if m.id == decision.memory_id), None)
            if existing is None:
                # The model named an id we didn't actually offer it; treat
                # as a fresh fact rather than trust an unverified id.
                return await _create(memory, decision, embedding, conversation_id)
            if existing.content.strip().lower() == decision.content.strip().lower():
                return ExtractionResult(saved=False)  # nothing actually changed
            memory.update_memory(
                existing.id, content=decision.content, importance=decision.importance,
                confidence=decision.confidence, embedding=embedding,
            )
            log.info("memory extraction: updated %s", existing.id[:8])
            return ExtractionResult(saved=True, content=decision.content)
        return await _create(memory, decision, embedding, conversation_id)
    except MemoryError:
        log.warning("memory extraction: write failed", exc_info=True)
        return ExtractionResult(saved=False)


async def _create(
    memory: MemoryService, decision: _Decision, embedding: list[float] | None, conversation_id: str
) -> ExtractionResult:
    category = decision.category or "important_fact"
    key = _usable_key(decision.key)  # the model's suggestion, or None
    kwargs = dict(
        source="auto", confidence=decision.confidence, importance=decision.importance,
        embedding=embedding, source_conversation_id=conversation_id,
    )
    try:
        memory.create_memory(category, key, decision.content or "", **kwargs)
    except MemoryConflict:
        # The model's suggested key collided with an existing (possibly
        # inactive) memory. `key=None` makes create_memory derive a fresh
        # one from the content itself, which cannot collide the same way.
        memory.create_memory(category, None, decision.content or "", **kwargs)
    log.info("memory extraction: created (%s)", category)
    return ExtractionResult(saved=True, content=decision.content)


def _usable_key(key: str | None) -> str | None:
    if not key:
        return None
    candidate = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return candidate[:64] or None
