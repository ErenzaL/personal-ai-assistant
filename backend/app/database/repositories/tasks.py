from __future__ import annotations

import sqlite3

from app.database.models import Task, TaskItem, TaskPriority, TaskStatus
from app.database.repositories._base import Repository, new_id, now


def _task(row: sqlite3.Row) -> Task:
    return Task(
        row["id"],
        row["title"],
        row["description"],
        row["due_at"],
        row["priority"],
        row["status"],
        row["remind_at"],
        row["completed_at"],
        row["created_at"],
        row["updated_at"],
        row["category"],
    )


def _task_item(row: sqlite3.Row) -> TaskItem:
    return TaskItem(
        row["id"],
        row["task_id"],
        row["text"],
        bool(row["is_completed"]),
        row["position"],
        row["created_at"],
        row["updated_at"],
    )


# Open first, then by due date (undated last), then by priority, then age.
_ORDER = """
    CASE status WHEN 'open' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END,
    due_at IS NULL,
    due_at,
    CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
    created_at
"""


class TaskRepository(Repository):
    """Personal tasks. All SQL for the tasks table lives here."""

    def create(
        self,
        title: str,
        description: str = "",
        due_at: str | None = None,
        *,
        priority: TaskPriority = "normal",
        remind_at: str | None = None,
        category: str = "",
    ) -> Task:
        ts = now()
        record = Task(new_id(), title, description, due_at, priority, "open", remind_at, None, ts, ts, category)
        self._write(
            """
            INSERT INTO tasks (id, title, description, due_at, priority, status, remind_at,
                               completed_at, created_at, updated_at, category)
            VALUES (?, ?, ?, ?, ?, 'open', ?, NULL, ?, ?, ?)
            """,
            (record.id, title, description, due_at, priority, remind_at, ts, ts, category),
        )
        return record

    def get(self, task_id: str) -> Task | None:
        row = self._one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task(row) if row else None

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
        has_due: bool | None = None,
        limit: int = 200,
    ) -> list[Task]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if due_after is not None:
            clauses.append("due_at >= ?")
            params.append(due_after)
        if due_before is not None:
            clauses.append("due_at < ?")
            params.append(due_before)
        if has_due is True:
            clauses.append("due_at IS NOT NULL")
        elif has_due is False:
            clauses.append("due_at IS NULL")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._all(f"SELECT * FROM tasks{where} ORDER BY {_ORDER} LIMIT ?", (*params, limit))
        return [_task(r) for r in rows]

    def due_between(self, start: str, end: str, *, status: TaskStatus = "open") -> list[Task]:
        """Tasks with a due date in [start, end), UTC ISO strings."""
        return self.list(status=status, due_after=start, due_before=end)

    def overdue(self, before: str) -> list[Task]:
        return self.list(status="open", due_before=before, has_due=True)

    def upcoming(self, after: str, *, status: TaskStatus = "open", limit: int = 200) -> list[Task]:
        """Open tasks due on or after `after`, plus every undated open task.
        `_ORDER` already sorts undated tasks after dated ones, so nothing
        with no due date is ever hidden -- it just sorts last."""
        rows = self._all(
            f"SELECT * FROM tasks WHERE status = ? AND (due_at IS NULL OR due_at >= ?) ORDER BY {_ORDER} LIMIT ?",
            (status, after, limit),
        )
        return [_task(r) for r in rows]

    def completed(self, *, limit: int = 200) -> list[Task]:
        """Completed tasks, newest completion first."""
        rows = self._all(
            "SELECT * FROM tasks WHERE status = 'completed' ORDER BY completed_at DESC, updated_at DESC LIMIT ?",
            (limit,),
        )
        return [_task(r) for r in rows]

    def due_for_reminder(self, before: str) -> list[Task]:
        """Open tasks whose reminder time has arrived (for later use)."""
        rows = self._all(
            "SELECT * FROM tasks WHERE status = 'open' AND remind_at IS NOT NULL AND remind_at <= ? ORDER BY remind_at",
            (before,),
        )
        return [_task(r) for r in rows]

    def update(self, task_id: str, **fields: object) -> Task | None:
        """Set the given columns. Pass None to clear a nullable column;
        omit a column to leave it alone."""
        allowed = ("title", "description", "due_at", "priority", "remind_at", "category")
        changes = {k: v for k, v in fields.items() if k in allowed}
        if not changes:
            return self.get(task_id)
        ts = now()
        assignments = ", ".join(f"{name} = ?" for name in changes)
        changed = self._write(
            f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
            (*changes.values(), ts, task_id),
        )
        return self.get(task_id) if changed else None

    def set_status(self, task_id: str, status: TaskStatus) -> Task | None:
        ts = now()
        completed_at = ts if status == "completed" else None
        changed = self._write(
            "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, completed_at, ts, task_id),
        )
        return self.get(task_id) if changed else None

    def search(self, text: str, *, status: TaskStatus | None = None, limit: int = 50) -> list[Task]:
        """Case-insensitive substring match on title and description."""
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        clauses = ["(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"]
        params: list[object] = [pattern, pattern]
        if status:
            clauses.append("status = ?")
            params.append(status)
        rows = self._all(
            f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY {_ORDER} LIMIT ?",
            (*params, limit),
        )
        return [_task(r) for r in rows]

    def delete(self, task_id: str) -> bool:
        """Hard delete, cascading to the task's own items. Not offered as a
        casual action in the UI -- see `TaskService.delete_task`."""
        return self._write("DELETE FROM tasks WHERE id = ?", (task_id,)) == 1

    # --- checklist items ---

    def add_item(self, task_id: str, text: str, *, position: int | None = None) -> TaskItem:
        ts = now()
        if position is None:
            row = self._one("SELECT COALESCE(MAX(position), -1) + 1 AS next FROM task_items WHERE task_id = ?", (task_id,))
            position = row["next"] if row else 0
        record = TaskItem(new_id(), task_id, text, False, position, ts, ts)
        self._write(
            """
            INSERT INTO task_items (id, task_id, text, is_completed, position, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (record.id, task_id, text, position, ts, ts),
        )
        return record

    def list_items(self, task_id: str) -> list[TaskItem]:
        rows = self._all("SELECT * FROM task_items WHERE task_id = ? ORDER BY position, created_at", (task_id,))
        return [_task_item(r) for r in rows]

    def items_progress(self, task_id: str) -> tuple[int, int]:
        """(completed, total) checklist items for one task."""
        row = self._one(
            "SELECT COUNT(*) AS total, COALESCE(SUM(is_completed), 0) AS done FROM task_items WHERE task_id = ?",
            (task_id,),
        )
        return (row["done"], row["total"]) if row else (0, 0)

    def get_item(self, item_id: str) -> TaskItem | None:
        row = self._one("SELECT * FROM task_items WHERE id = ?", (item_id,))
        return _task_item(row) if row else None

    def update_item(self, item_id: str, *, text: str) -> TaskItem | None:
        ts = now()
        changed = self._write(
            "UPDATE task_items SET text = ?, updated_at = ? WHERE id = ?",
            (text, ts, item_id),
        )
        return self.get_item(item_id) if changed else None

    def set_item_completed(self, item_id: str, is_completed: bool) -> TaskItem | None:
        ts = now()
        changed = self._write(
            "UPDATE task_items SET is_completed = ?, updated_at = ? WHERE id = ?",
            (1 if is_completed else 0, ts, item_id),
        )
        return self.get_item(item_id) if changed else None

    def delete_item(self, item_id: str) -> bool:
        return self._write("DELETE FROM task_items WHERE id = ?", (item_id,)) == 1

    def reorder_items(self, task_id: str, item_ids: list[str]) -> list[TaskItem]:
        """Sets each listed item's position to its index in `item_ids`.
        Ids that do not belong to `task_id` are ignored."""
        ts = now()
        with self.conn:
            for position, item_id in enumerate(item_ids):
                self.conn.execute(
                    "UPDATE task_items SET position = ?, updated_at = ? WHERE id = ? AND task_id = ?",
                    (position, ts, item_id, task_id),
                )
        return self.list_items(task_id)
