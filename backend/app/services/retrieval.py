"""Choosing which stored memories, if any, belong in a turn's prompt.

Primary path is semantic: `EmbeddingMemoryRetriever` embeds the message and
ranks stored memories by cosine similarity, so "I want to focus on data
science now" can find a memory worded "interested in becoming a data
analyst" with no shared words at all. `KeywordMemoryRetriever` (the original
term-overlap matcher) is kept as the automatic fallback for when embeddings
are unavailable -- no key, a provider without an embedding model (Groq), or a
transient failure -- so retrieval degrades rather than goes silent.

`is_personal()` still gates whether to look at all, even on the semantic
path. That is a calibration finding, not a stylistic choice: measured
against this project's own data, gemini-embedding-001 puts nearly all
short text pairs in a narrow 0.5-0.7 cosine band regardless of relevance --
"hi" scores *higher* against an unrelated memory than a real match sometimes
does against its own. There is no absolute similarity value that reliably
means "irrelevant" here. What the embeddings are genuinely good at, and what
they are used for, is *ranking*: among memories once we've decided to look,
the right one reliably comes out on top. Deciding *whether* to look stays a
cheap, well-tested heuristic; deciding *what* is relevant is semantic. That
split is not "keyword matching as the retrieval method" -- nothing is scored
or selected by shared words on the primary path -- it is a pre-filter in
front of it, same as a spam filter running before a search ranker.

`MemoryRetriever` is a Protocol so a future implementation can replace either
without touching the chat service.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Iterable, Protocol

from app.database.models import Memory
from app.services.embeddings import cosine_similarity
from app.services.llm import LLMService
from app.services.memory import MemoryService

log = logging.getLogger("app.memory")

# Below this, treat a similarity as noise (a corrupted vector, or the 0.0
# `cosine_similarity` returns for a dimension mismatch) rather than a real
# signal. Not a precision floor -- see the module docstring for why one
# would not work reliably with this embedding model.
SIMILARITY_FLOOR = 0.35

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


# A trailing contraction/possessive suffix carries no meaning of its own
# ("what's" -> "what", "don't" -> "don", "you're" -> "you"), so it is
# stripped before the stopword check; otherwise "what's" survives as a term
# distinct from "what" and quietly defeats matching on short questions.
_CONTRACTION_SUFFIX = re.compile(r"'(s|t|re|ve|ll|d|m)$")


def _terms(text: str) -> set[str]:
    """Distinctive lowercase terms, with a crude singular form so
    'meetings' matches 'meeting'."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9']+", text.lower()):
        word = _CONTRACTION_SUFFIX.sub("", word).strip("'")
        if len(word) < 2 or word in _STOPWORDS:
            continue
        out.add(word)
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            out.add(word[:-1])
    return out


class MemoryRetriever(Protocol):
    """Selects the memories to put in the prompt for one message."""

    async def retrieve(self, message: str) -> list[Memory]: ...


class KeywordMemoryRetriever:
    """Term-overlap retrieval over active memories. No I/O of its own; async
    only so it is interchangeable with the embedding retriever that wraps it
    as a fallback."""

    def __init__(self, memory: MemoryService) -> None:
        self._memory = memory

    async def retrieve(self, message: str) -> list[Memory]:
        if not is_personal(message):
            log.debug("memory: skipped (not a personal question)")
            return []

        query = _terms(message)
        planning = bool(_PLANNING.search(message))
        base_needed = MIN_OVERLAP_PLANNING if planning else MIN_OVERLAP_GENERAL
        # A short, direct question ("What is my name?") can reduce to a
        # single distinctive term once stopwords are stripped. Requiring
        # more shared terms than the query even has would make it
        # impossible to ever match, no matter what is stored, so the
        # threshold never exceeds the query's own size.
        needed = min(base_needed, len(query)) if query else base_needed
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
        selected = _cap(record for _, record in scored)
        _log_used(selected, "keyword")
        return selected


def _cap(ranked: "Iterable[Memory]") -> list[Memory]:
    """Top N, within a character budget -- shared by every retriever so the
    prompt's memory section never grows unbounded regardless of how a
    memory was ranked."""
    selected: list[Memory] = []
    budget = MAX_CHARS
    for record in ranked:
        if len(selected) >= MAX_MEMORIES:
            break
        if len(record.content) > budget:
            continue
        selected.append(record)
        budget -= len(record.content)
    return selected


def _log_used(selected: list[Memory], method: str) -> None:
    # Log identifiers only: never the content of a memory.
    if selected:
        log.info("memory: %d used via %s %s", len(selected), method, [(m.id[:8], m.category) for m in selected])


class EmbeddingMemoryRetriever:
    """Semantic retrieval: embeds the message, ranks active memories by
    cosine similarity to their own stored embedding, and falls back to
    keyword matching whenever an embedding cannot be produced -- no key, a
    provider without an embedding model, a transient failure, or simply no
    memory having one yet (a fresh install, before any extraction has run)."""

    def __init__(self, memory: MemoryService, llm: LLMService, fallback: MemoryRetriever) -> None:
        self._memory = memory
        self._llm = llm
        self._fallback = fallback

    async def retrieve(self, message: str) -> list[Memory]:
        # See the module docstring: the embedding space itself does not
        # separate relevant from irrelevant at the absolute level, so this
        # gate still decides *whether* to look.
        if not is_personal(message):
            log.debug("memory: skipped (not a personal question)")
            return []

        pool = self._memory.list_with_embeddings()
        if not pool:
            return await self._fallback.retrieve(message)

        query_vector = await self._llm.embed(message, task="query")
        if query_vector is None:
            log.info("memory: embedding unavailable, falling back to keyword matching")
            return await self._fallback.retrieve(message)

        scored = [(cosine_similarity(query_vector, m.embedding), m) for m in pool if m.embedding]
        scored = [pair for pair in scored if pair[0] >= SIMILARITY_FLOOR]
        scored.sort(key=lambda pair: (-pair[0], -pair[1].importance, pair[1].updated_at))
        selected = _cap(record for _, record in scored)
        _log_used(selected, "embedding")
        return selected


def format_memories(memories: list[Memory]) -> list[str]:
    """One short line per memory for the prompt's memory section."""
    return [f"({m.category}) {m.content}" for m in memories]


def get_retriever(db: sqlite3.Connection, llm: LLMService) -> MemoryRetriever:
    """Semantic retrieval backed by a keyword fallback. Swap the top-level
    implementation here to change retrieval everywhere."""
    keyword = KeywordMemoryRetriever(MemoryService(db))
    return EmbeddingMemoryRetriever(MemoryService(db), llm, fallback=keyword)
