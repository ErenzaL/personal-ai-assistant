-- Adds a free-text category to tasks, and a checklist-items table so a task
-- can have its own independently-completable sub-steps with their own order.
-- Completing every item never completes the parent task automatically --
-- that stays a deliberate, separate action.

ALTER TABLE tasks ADD COLUMN category TEXT NOT NULL DEFAULT '';

CREATE TABLE task_items (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    is_completed INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX idx_task_items_task ON task_items(task_id, position);
