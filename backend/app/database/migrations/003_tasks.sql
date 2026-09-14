-- Finalise the tasks table: add priority and remind_at, and rename the
-- 'done' status to 'completed'. SQLite cannot alter a CHECK constraint, so
-- the table is rebuilt and existing rows are carried across.

CREATE TABLE tasks_new (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    due_at       TEXT,                                   -- ISO 8601 UTC; interpreted/displayed in local time
    priority     TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'cancelled')),
    remind_at    TEXT,                                   -- ISO 8601 UTC, must not be after due_at
    completed_at TEXT,                                   -- kept so finished work stays in history
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

INSERT INTO tasks_new (id, title, description, due_at, priority, status, remind_at, completed_at, created_at, updated_at)
SELECT id,
       title,
       description,
       due_at,
       'normal',
       CASE status WHEN 'done' THEN 'completed' ELSE status END,
       NULL,
       completed_at,
       created_at,
       updated_at
FROM tasks;

DROP TABLE tasks;
ALTER TABLE tasks_new RENAME TO tasks;

CREATE INDEX idx_tasks_status_due ON tasks(status, due_at);
CREATE INDEX idx_tasks_remind ON tasks(status, remind_at);
