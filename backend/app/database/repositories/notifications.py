from __future__ import annotations

import sqlite3

from app.database.models import Notification
from app.database.repositories._base import Repository, new_id, now


def _notification(row: sqlite3.Row) -> Notification:
    return Notification(
        row["id"],
        row["kind"],
        row["title"],
        row["body"],
        row["reference_id"],
        row["sent_at"],
        row["acknowledged_at"],
    )


class NotificationRepository(Repository):
    """History of notifications shown to the user."""

    def record(self, kind: str, title: str, body: str = "", reference_id: str | None = None) -> Notification:
        record = Notification(new_id(), kind, title, body, reference_id, now(), None)
        self._write(
            """
            INSERT INTO notification_history (id, kind, title, body, reference_id, sent_at, acknowledged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.kind,
                record.title,
                record.body,
                record.reference_id,
                record.sent_at,
                record.acknowledged_at,
            ),
        )
        return record

    def list(self, limit: int = 50) -> list[Notification]:
        rows = self._all("SELECT * FROM notification_history ORDER BY sent_at DESC LIMIT ?", (limit,))
        return [_notification(r) for r in rows]

    def acknowledge(self, notification_id: str) -> bool:
        return self._write(
            "UPDATE notification_history SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
            (now(), notification_id),
        ) == 1

    def was_sent(self, kind: str, reference_id: str, since: str | None = None) -> bool:
        """True if a notification of this kind for this reference was already
        sent (optionally only counting those at or after `since`). Lets the
        reminder logic avoid nagging twice."""
        if since is None:
            row = self._one(
                "SELECT 1 FROM notification_history WHERE kind = ? AND reference_id = ? LIMIT 1",
                (kind, reference_id),
            )
        else:
            row = self._one(
                "SELECT 1 FROM notification_history WHERE kind = ? AND reference_id = ? AND sent_at >= ? LIMIT 1",
                (kind, reference_id, since),
            )
        return row is not None

    def prune(self, older_than: str) -> int:
        """Delete entries sent before `older_than` (ISO 8601). Returns count removed."""
        return self._write("DELETE FROM notification_history WHERE sent_at < ?", (older_than,))
