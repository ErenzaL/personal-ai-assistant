"""SQLite persistence layer.

Layout:
  paths.py        where the database file lives (per-OS app-data folder)
  connection.py   open connections, FastAPI dependency, one-time init
  migrations.py   apply numbered SQL files from migrations/ in order
  models.py       plain dataclasses returned by repositories
  repositories/   one module per table group; the only place SQL is written

Routes and services never write SQL. They ask a repository.
"""

from app.database.connection import connect, get_db, init_database
from app.database.paths import default_database_path

__all__ = ["connect", "default_database_path", "get_db", "init_database"]
