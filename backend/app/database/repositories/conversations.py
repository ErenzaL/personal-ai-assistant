from __future__ import annotations

import sqlite3

from app.database.models import Conversation, Message, MessageRole
from app.database.repositories._base import Repository, new_id, now


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(row["id"], row["title"], row["created_at"], row["updated_at"])


def _message(row: sqlite3.Row) -> Message:
    return Message(row["id"], row["conversation_id"], row["role"], row["content"], row["created_at"])


class ConversationRepository(Repository):
    """Conversations and the messages inside them."""

    def create(self, title: str | None = None) -> Conversation:
        ts = now()
        record = Conversation(new_id(), title, ts, ts)
        self._write(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (record.id, record.title, record.created_at, record.updated_at),
        )
        return record

    def get(self, conversation_id: str) -> Conversation | None:
        row = self._one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        return _conversation(row) if row else None

    def list(self, limit: int = 50) -> list[Conversation]:
        rows = self._all("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [_conversation(r) for r in rows]

    def rename(self, conversation_id: str, title: str | None) -> bool:
        return self._write(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now(), conversation_id),
        ) == 1

    def delete(self, conversation_id: str) -> bool:
        """Deletes the conversation and, via ON DELETE CASCADE, its messages."""
        return self._write("DELETE FROM conversations WHERE id = ?", (conversation_id,)) == 1

    # --- messages ---

    def add_message(self, conversation_id: str, role: MessageRole, content: str) -> Message:
        ts = now()
        record = Message(new_id(), conversation_id, role, content, ts)
        with self.conn:
            self.conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (record.id, record.conversation_id, record.role, record.content, record.created_at),
            )
            self.conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, conversation_id))
        return record

    def list_messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        """Messages oldest first. With `limit`, the most recent N (still oldest first)."""
        if limit is None:
            rows = self._all(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
                (conversation_id,),
            )
        else:
            rows = self._all(
                """
                SELECT * FROM (
                    SELECT *, rowid AS seq FROM messages WHERE conversation_id = ?
                    ORDER BY created_at DESC, rowid DESC LIMIT ?
                ) ORDER BY created_at, seq
                """,
                (conversation_id, limit),
            )
        return [_message(r) for r in rows]

    def count_messages(self, conversation_id: str) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?", (conversation_id,))
        return int(row["n"]) if row else 0
