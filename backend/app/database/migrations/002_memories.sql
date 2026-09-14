-- Long-term personal memory: durable facts about the user, independent of any
-- conversation. Rows are deactivated, not deleted, so history is auditable.

CREATE TABLE memories (
    id         TEXT PRIMARY KEY,
    category   TEXT NOT NULL CHECK (category IN (
                   'profile', 'preference', 'routine', 'goal',
                   'project', 'person', 'important_fact')),
    key        TEXT NOT NULL,                       -- stable identifier within the category, e.g. preferred_meeting_time
    content    TEXT NOT NULL,                       -- the fact, in plain language
    source     TEXT NOT NULL DEFAULT 'user',        -- who asserted it: user | assistant | import
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (category, key)
);
CREATE INDEX idx_memories_active_category ON memories(is_active, category);
