"""Math and encoding shared by anything that stores or compares embeddings.

Provider-specific embedding calls live on `LLMService.embed()` (see
`services/llm/base.py` and `services/llm/gemini.py`); this module has no
network code and no provider knowledge, only the pure functions every caller
needs: turning a vector into what SQLite can store, and comparing two.
"""

from __future__ import annotations

import json
import math

# gemini-embedding-001 at the dimensionality this app requests. Vectors of a
# different length (a future provider, or a stale row) are simply treated as
# incomparable rather than crashing.
EXPECTED_DIMENSIONS = 768


def encode(vector: list[float]) -> str:
    """Embedding -> the TEXT the `embedding` column stores."""
    return json.dumps(vector)


def decode(value: str | None) -> list[float] | None:
    """The stored TEXT -> an embedding, or None if there is nothing usable.
    Never raises: a corrupted or foreign-shaped value is just "no embedding",
    which callers already handle by falling back to keyword matching."""
    if not value:
        return None
    try:
        vector = json.loads(value)
    except ValueError:
        return None
    if not isinstance(vector, list) or not vector or not all(isinstance(x, (int, float)) for x in vector):
        return None
    return [float(x) for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """1.0 = identical direction, 0.0 = unrelated, -1.0 = opposite. 0.0 for
    mismatched lengths or a zero vector, rather than raising: a bad vector
    should just fail to match anything, not take retrieval down."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
