from __future__ import annotations

import sqlite3

from app.database.models import Task, TaskPriority, TaskStatus
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
    ) -> Task:
        ts = now()
        record = Task(new_id(), title, description, due_at, priority, "open", remind_at, None, ts, ts)
        self._write(
            """
            INSERT INTO tasks (id, title, description, due_at, priority, status, remind_at,
                               completed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?, NULL, ?, ?)
            """,
            (record.id, title, description, due_at, priority, remind_at, ts, ts),
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
        allowed = ("title", "description", "due_at", "priority", "remind_at")
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
        """Hard delete. Not used by normal flows: tasks are cancelled instead."""
        return self._write("DELETE FROM tasks WHERE id = ?", (task_id,)) == 1
