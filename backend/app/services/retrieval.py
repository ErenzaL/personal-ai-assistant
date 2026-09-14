"""Choosing which stored memories, if any, belong in a turn's prompt.

Deliberately cheap and deterministic: no extra LLM call and no embeddings, so
a normal question costs exactly what it did before. The flow is

    is_personal()   cheap gate: could stored memory matter here at all?
    score           term overlap + a category bonus for planning questions
    cap             top N, within a character budget

Matching is lexical, so it finds "meetings after 2 PM" for "a good time for a
meeting" but not for a paraphrase with no shared words. `MemoryRetriever` is a
Protocol, so an embedding- or LLM-based retriever can replace
`KeywordMemoryRetriever` later without touching the chat service.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Protocol

from app.database.models import Memory
from app.services.memory import MemoryService

log = logging.getLogger("app.memory")

# Keep the injected block tiny: a handful of short facts, never the database.
MAX_MEMORIES = 3
MAX_CHARS = 600

# How many distinctive terms a memory must share with the message to qualify.
# A planning question ("when should I meet?") is already about the user's
# arrangements, so one solid term is enough. Any other personal message needs
# two, so that a single common word ("main", "time") cannot drag in an
# unrelated memory.
MIN_OVERLAP_PLANNING = 1
MIN_OVERLAP_GENERAL = 2

# Ranking only: among equally-matching memories, the categories that govern
# scheduling come first on a planning question.
TERM_WEIGHT = 2
PLANNING_BONUS = 1
PLANNING_CATEGORIES = ("preference", "routine")

# The message is about the user personally if it refers to them...
_PERSONAL = re.compile(r"\b(i|i'm|im|i'd|i'll|i've|me|my|mine|myself|we|our|us)\b", re.IGNORECASE)
# ...or is about arranging something in their life.
_PLANNING = re.compile(
    r"\b(schedul\w*|meet\w*|appointment\w*|calendar|event\w*|remind\w*|plan\w*|book\w*|"
    r"agenda|availab\w*|free time|busy|deadline\w*|task\w*|todo|to-do|routine\w*|"
    r"morning|afternoon|evening|tonight|tomorrow|today|weekend|next week)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "a", "about", "after", "an", "and", "any", "are", "as", "at", "be", "been", "best", "but", "by", "can",
    "could", "did", "do", "does", "for", "from", "get", "give", "good", "has", "have", "how", "i", "if",
    "in", "is", "it", "its", "just", "know", "like", "make", "me", "might", "more", "most", "much", "my",
    "need", "new", "not", "of", "on", "one", "or", "our", "out", "please", "should", "so", "some", "tell",
    "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "up", "us",
    "use", "want", "was", "we", "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your",
}


def is_personal(text: str) -> bool:
    """Could stored personal memory plausibly matter for this message?

    False for general-knowledge questions ("What is Kubernetes?"), which then
    skip retrieval entirely: no database read, no prompt section.
    """
    return bool(_PERSONAL.search(text) or _PLANNING.search(text))


def _terms(text: str) -> set[str]:
    """Distinctive lowercase terms, with a crude singular form so
    'meetings' matches 'meeting'."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9']+", text.lower()):
        word = word.strip("'")
        if len(word) < 2 or word in _STOPWORDS:
            continue
        out.add(word)
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            out.add(word[:-1])
    return out


class MemoryRetriever(Protocol):
    """Selects the memories to put in the prompt for one message."""

    def retrieve(self, message: str) -> list[Memory]: ...


class KeywordMemoryRetriever:
    """Term-overlap retrieval over active memories."""

    def __init__(self, memory: MemoryService) -> None:
        self._memory = memory

    def retrieve(self, message: str) -> list[Memory]:
        if not is_personal(message):
            log.debug("memory: skipped (not a personal question)")
            return []

        query = _terms(message)
        planning = bool(_PLANNING.search(message))
        needed = MIN_OVERLAP_PLANNING if planning else MIN_OVERLAP_GENERAL
        scored: list[tuple[int, Memory]] = []
        for record in self._memory.list_memories():
            haystack = _terms(f"{record.key.replace('_', ' ')} {record.content}")
            overlap = len(query & haystack)
            if overlap < needed:
                continue
            score = TERM_WEIGHT * overlap
            if planning and record.category in PLANNING_CATEGORIES:
                score += PLANNING_BONUS
            scored.append((score, record))

        scored.sort(key=lambda pair: (-pair[0], -pair[1].confidence, pair[1].updated_at))

        selected: list[Memory] = []
        budget = MAX_CHARS
        for _, record in scored[:MAX_MEMORIES]:
            if len(record.content) > budget:
                break
            selected.append(record)
            budget -= len(record.content)

        # Log identifiers only: never the content of a memory.
        if selected:
            log.info(
                "memory: %d used %s",
                len(selected),
                [(m.id[:8], m.category) for m in selected],
            )
        return selected


def format_memories(memories: list[Memory]) -> list[str]:
    """One short line per memory for the prompt's memory section."""
    return [f"({m.category}) {m.content}" for m in memories]


def get_retriever(db: sqlite3.Connection) -> MemoryRetriever:
    """Swap the implementation here to change retrieval everywhere."""
    return KeywordMemoryRetriever(MemoryService(db))
