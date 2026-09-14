"""Repositories: the only code that writes SQL.

Each takes an open `sqlite3.Connection` and commits its own writes. Get one
per request through the `get_db` dependency.
"""

from app.database.repositories.conversations import ConversationRepository
from app.database.repositories.memories import MemoryRepository
from app.database.repositories.notes import NoteRepository
from app.database.repositories.notifications import NotificationRepository
from app.database.repositories.settings import SettingsRepository
from app.database.repositories.tasks import TaskRepository

__all__ = [
    "ConversationRepository",
    "MemoryRepository",
    "NoteRepository",
    "NotificationRepository",
    "SettingsRepository",
    "TaskRepository",
]
