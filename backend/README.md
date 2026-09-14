# Backend

Python FastAPI service that will host assistant logic (LLM calls, calendar sync,
local SQLite storage). Currently exposes `GET /health` only.

## Layout

```
app/
  main.py          FastAPI app, CORS, router registration, shutdown hook
  config.py        Settings from environment / backend/.env (API keys live here)
  api/             HTTP routers (health.py, chat.py, conversations.py, memories.py)
  services/
    chat.py        ConversationService + ChatService (chat turns)
    context.py     PromptContext: how a turn's prompt is assembled
    memory.py      MemoryService: long-term personal memory (validation, CRUD, search)
    memory_commands.py  remember / recall / forget spoken in chat
    retrieval.py   picks the few relevant memories for a turn's prompt
    preferences.py assistant name + response style (stored in `settings`)
    tasks.py       TaskService: create/list/update/complete/cancel + validation
    tools/         structured tools: base.py (registry, validation), tasks.py, selector.py
    timeutil.py    local time <-> UTC, local day/week windows
    llm/
      base.py      LLMService interface (generate, stream), LLMError kinds
      gemini.py    Gemini provider (REST)
      groq.py      Groq provider (OpenAI-compatible REST)
      factory.py   Picks the provider from LLM_PROVIDER
      prompts.py   System prompt
  database/
    paths.py       DB file location (per-OS app-data folder)
    connection.py  connect(), get_db dependency, init_database()
    migrations.py  applies migrations/NNN_*.sql in order
    migrations/    001_initial.sql (conversations, messages, notes, tasks, settings, notification_history)
                   002_memories.sql (long-term personal memory)
    models.py      dataclasses mirroring rows
    repositories/  one class per table group; the only place SQL lives
```

## LLM setup

```sh
cp .env.example .env
# edit .env: set GEMINI_API_KEY (or set LLM_PROVIDER=groq and GROQ_API_KEY)
```

Keys are read on the backend only and never sent to the desktop app. On
startup the log prints `LLM provider: gemini (API key set)`; if it says
`MISSING`, `/chat` answers 503 with an explanation until you fix `.env`.

## Run (macOS)

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open http://127.0.0.1:8000/health and expect `{"status":"ok"}`.
Interactive docs: http://127.0.0.1:8000/docs

## CORS

`app/main.py` allows the origins the Tauri webview uses (`http://localhost:1420`
in dev, `tauri://localhost` in the packaged macOS app). The server binds to
127.0.0.1 only; CORS just lets the webview read responses.

## Database

SQLite, created automatically on first start (folder, file, schema). Location:

| Where | Path |
|---|---|
| macOS (default) | `~/Library/Application Support/PersonalAIAssistant/assistant.db` |
| Override | `DATABASE_PATH=...` in `.env` (e.g. `./data/dev.db` for a throwaway dev DB) |

The startup log prints the path in use (`INFO: database: ...`). Inspect it with
`sqlite3 "<path>" .tables`. To reset in development, stop the server and delete
the file (and its `-wal`/`-shm` siblings).

Schema changes: add `app/database/migrations/002_<name>.sql`; it is applied
once at the next start and recorded in `schema_migrations`. Never edit an
applied migration.

Routes never write SQL. Use a repository with the `get_db` dependency:

```python
from fastapi import Depends
import sqlite3
from app.database import get_db
from app.database.repositories import TaskRepository

@router.get("/tasks")
def list_tasks(db: sqlite3.Connection = Depends(get_db)):
    return TaskRepository(db).list(status="open")
```

## Personal memory

Durable facts about the user (`memories` table), separate from conversation
history. Categories: profile, preference, routine, goal, project, person,
important_fact. `(category, key)` is unique; rows are deactivated rather than
deleted. Nothing is remembered automatically; use the API:

```
GET    /memories                      active memories (filters: category, q, key, include_inactive)
POST   /memories                      {category, key, content, source?, confidence?}
GET    /memories/{id}
PATCH  /memories/{id}                 {content?, source?, confidence?}
DELETE /memories/{id}                 deactivate (soft delete)
POST   /memories/{id}/activate
GET    /memories/categories
POST   /memories/deactivate-all       soft-delete every active memory
GET    /settings                      assistant name + response style
PATCH  /settings                      {assistant_name?, response_style?}

GET    /tasks?filter=open             today|tomorrow|week|overdue|open|completed|cancelled|all
POST   /tasks                         {title, description?, due_at?, priority?, remind_at?}
GET    /tasks/{id}
PATCH  /tasks/{id}                    {title?, description?, due_at?, priority?, remind_at?, clear?}
POST   /tasks/{id}/complete           keeps the row, sets completed_at
POST   /tasks/{id}/cancel
POST   /tasks/{id}/reopen
```

Task dates are given in **local** time (`2026-09-15T18:00:00`) and stored as
UTC. In chat, the assistant reaches the same service through five structured tools
(`tasks.list`, `tasks.create`, `tasks.update`, `tasks.complete`,
`tasks.cancel`) in `services/tools/`. Tool execution is separate from writing
the answer: a tool runs first, its JSON result goes into the prompt, and the
reply is written from that result. See docs/architecture.md.

`POST /memories` may omit `key`: the backend derives one from the content, so
UI callers never invent internal values.

In chat, "Remember that …", "What do you remember about me / my preferences?"
and "Forget …" are handled by `services/memory_commands.py` (see
docs/architecture.md). When answering ordinary questions, `services/retrieval.py`
adds at most three relevant active memories to the prompt, and nothing at all
for general-knowledge questions.

## Started by the desktop app

For daily use nothing has to be started by hand. When Dully launches it looks
for a backend on `127.0.0.1:8000`; if one is already running (for example the
`--reload` server above) it uses that, otherwise it runs `run_backend.py` from this
folder's `.venv`, bound to localhost only, restarts it up to three times if it
crashes, and stops it when Dully quits. The script also watches the app and
shuts down on its own if the app disappears, even after a force quit. Its output goes to `backend.log` in
the app data folder (`~/Library/Application Support/com.linerenza.personal-ai-assistant/`).

Where the backend lives is taken from, in order: the `DULLY_BACKEND_DIR`
environment variable, a `backend-path.txt` in that app data folder, or the
repository the binary sits in (development builds). An installed copy needs
the text file once.

## Packaged for the release build

`scripts/build-backend.sh` (run by `scripts/build-release.sh`) turns this
folder into one executable that ships inside `Dully.app`. It reads the API
key from `~/Library/Application Support/PersonalAIAssistant/.env`, not from
`backend/.env`. See `docs/release.md`.
