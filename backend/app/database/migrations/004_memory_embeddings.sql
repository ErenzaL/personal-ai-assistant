-- Automatic, semantic personal memory: embeddings for similarity search, an
-- importance signal distinct from confidence, and provenance back to the
-- conversation a memory came from (kept for audit; a deleted conversation
-- must not take its memories with it, so this is SET NULL, not CASCADE --
-- conversation history and long-term memory are deliberately independent).

ALTER TABLE memories ADD COLUMN importance REAL NOT NULL DEFAULT 0.5
    CHECK (importance >= 0.0 AND importance <= 1.0);

-- JSON-encoded array of floats (e.g. "[0.012, -0.043, ...]"), or NULL when no
-- embedding could be generated (provider without embedding support, or a
-- transient failure). NULL rows fall back to keyword matching at retrieval.
ALTER TABLE memories ADD COLUMN embedding TEXT DEFAULT NULL;

ALTER TABLE memories ADD COLUMN source_conversation_id TEXT DEFAULT NULL
    REFERENCES conversations(id) ON DELETE SET NULL;

CREATE INDEX idx_memories_source_conversation ON memories(source_conversation_id);

-- SQLite cannot add a CHECK constraint to an existing column, so the new
-- 'auto' source value (passively extracted, as opposed to a memory the user
-- explicitly typed into the old manual-add form) is accepted at the
-- application layer in app/services/memory.py, not enforced here.
