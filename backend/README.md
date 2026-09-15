# Backend

Python FastAPI service hosting all of Dully's assistant logic: LLM calls,
personal memory, calendar and Gmail tools, and local SQLite storage. The
desktop app is the only client; nothing here is exposed beyond `127.0.0.1`.

## Layout

```
app/
  main.py          FastAPI app, CORS, router registration, shutdown hook
  config.py        Settings from environment / backend/.env (API keys live here)
  api/             HTTP routers (health, chat, conversations, memories, settings, tasks, gmail)
  services/
    chat.py        ConversationService + ChatService (chat turns)
    context.py     PromptContext: how a turn's prompt is assembled
    memory.py      MemoryService: durable facts about the user (schema, CRUD, search)
    memory_extraction.py  decides what's worth remembering after each message,
                   and whether it updates an existing memory or is new
    memory_commands.py  explicit "what do you remember" / "forget ..." in chat
    embeddings.py  cosine similarity + encode/decode for stored memory vectors
    retrieval.py   semantic search over memory embeddings for a turn's prompt
                   (falls back to keyword matching if no embedding is available)
    preferences.py assistant name, response style, memory on/off, and more (in `settings`)
    tasks.py       TaskService: create/list/update/complete/cancel + validation
    gmail_service.py  Google OAuth (Desktop app flow) and the Gmail API calls
                   (list/search/get) behind it -- read-only, see Gmail below
    tools/         structured tools the assistant can call:
                     base.py       registry, argument validation, result rendering
                     selector.py   one completion -> which tool (if any) + arguments
                     tasks.py      tasks.list/create/update/complete/cancel
                     calendar.py   calendar.read/propose_event (client-executed, see below)
                     gmail.py      gmail.recent/search/read/draft_reply
    timeutil.py    local time <-> UTC, local day/week windows
    llm/
      base.py      LLMService interface (generate, stream, embed), LLMError kinds
      gemini.py    Gemini provider (REST) -- chat completions and embeddings
      groq.py      Groq provider (OpenAI-compatible REST) -- chat only, no embeddings
      factory.py   Picks the provider from LLM_PROVIDER
      prompts.py   Identity prompt: what Dully is, how to use each kind of result
  database/
    paths.py       DB file location (per-OS app-data folder)
    connection.py  connect(), get_db dependency, init_database()
    migrations.py  applies migrations/NNN_*.sql in order
    migrations/    001_initial, 002_memories, 003_tasks, 004_memory_embeddings
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
Personal-memory retrieval and extraction need Gemini specifically for
embeddings (`GeminiService.embed`); on Groq they fall back to keyword
matching, since Groq has no embedding endpoint.

## Run (macOS)

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open http://127.0.0.1:8000/health and expect `{"status":"ok","app":"dully"}`.
Interactive docs: http://127.0.0.1:8000/docs

## CORS

`app/main.py` allows the origins the Tauri webview uses (`http://localhost:1420`
in dev, `tauri://localhost` in the packaged macOS app), GET/POST/PATCH/DELETE
only. The server binds to 127.0.0.1 only; CORS just lets the webview read
responses.

## Database

SQLite, created automatically on first start (folder, file, schema). Location:

| Where | Path |
|---|---|
| macOS (default) | `~/Library/Application Support/PersonalAIAssistant/assistant.db` |
| Override | `DATABASE_PATH=...` in `.env` (e.g. `./data/dev.db` for a throwaway dev DB) |

The startup log prints the path in use (`INFO: database: ...`). Inspect it with
`sqlite3 "<path>" .tables`. To reset in development, stop the server and delete
the file (and its `-wal`/`-shm` siblings).

Schema changes: add `app/database/migrations/NNN_<name>.sql`; it is applied
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

Durable facts about the user (`memories` table: category, key, content,
importance, confidence, an embedding vector, and which conversation it came
from), kept separate from conversation history. After every user message,
one LLM call decides whether anything is worth keeping and, if so, whether
it's new or an update to an existing memory found by semantic similarity --
"I want to focus on data science now" updates a career-direction memory
instead of creating a duplicate. Nothing from a tool result (a calendar
event, a Gmail message) or the assistant's own reply ever reaches this step;
only what the user actually typed does. Turned off from Settings, or:

```
PATCH  /settings                      {memory_enabled: false, ...}
```

Before answering, the user's message is embedded and compared against stored
memory embeddings (`services/retrieval.py`), so a paraphrase can still find
the right memory with no shared words. If no embedding is available for a
given memory or the active LLM provider doesn't support embeddings, matching
falls back to keyword overlap for that lookup rather than finding nothing.

Manual endpoints still exist for the settings UI's review/edit/forget flow
(nothing there creates a memory anymore -- that's automatic now):

```
GET    /memories                      active memories (filters: category, q, key, include_inactive)
GET    /memories/{id}
PATCH  /memories/{id}                 {content?, source?, confidence?}
DELETE /memories/{id}                 deactivate (soft delete)
POST   /memories/{id}/activate
GET    /memories/categories
POST   /memories/deactivate-all       soft-delete every active memory
POST   /memories                      {category, key, content, source?, confidence?} -- still works, unused by the UI
```

In chat, "What do you remember about me / my preferences?" and "Forget …"
are still handled by `services/memory_commands.py` as explicit, deterministic
commands; saving a fact by asking is no longer a separate command, it's
whatever the automatic extraction above already does.

## Calendar

Read and write access to macOS Calendar (iCloud, Google, anything else
System Settings knows about) through Apple's EventKit -- no Google OAuth,
no stored Apple credentials. EventKit only exists on the native (Tauri/Rust)
side, so `calendar.read` and `calendar.propose_event` are the one pair of
tools marked `execution=CLIENT` in `services/tools/base.py`: the backend
picks the tool and validates its arguments, the desktop app runs it and
posts the result back, and the backend never touches a calendar itself. See
[docs/calendar-design.md](../docs/calendar-design.md). `calendar.propose_event`
only *prepares* an event -- the desktop app shows a Confirm/Edit/Cancel card,
and only Confirm calls EventKit to create it.

## Gmail

Read-only access via Google OAuth 2.0 (`services/gmail_service.py`), scope
fixed at `https://www.googleapis.com/auth/gmail.readonly` -- nothing broader
is ever requested, and no send/modify/delete call exists in this codebase.

**Setup**, once per machine:

1. In [Google Cloud Console](https://console.cloud.google.com), create an
   OAuth client ID of type **Desktop app** and download its JSON.
2. Save it as `backend/secrets/gmail_credentials.json` for development
   (git-ignored), or `~/Library/Application Support/PersonalAIAssistant/gmail_credentials.json`
   for a packaged build (which has no source tree to put `backend/secrets/`
   in). Either location works in development; only the app-data one works
   once packaged.
3. In Settings → Gmail, click **Connect Gmail**. This opens your browser for
   Google sign-in and blocks the request until you finish (or up to three
   minutes) -- call it from a sync route or a background task, never
   directly inside an `async def` route.
4. Under **OAuth consent screen → Test users**, add your own Google account,
   or the sign-in is blocked as unverified.

The resulting token is written to
`~/Library/Application Support/PersonalAIAssistant/gmail_token.json` (0600),
refreshed automatically when it's near expiry, and re-used silently on every
later launch -- connecting again is never required unless it's revoked.
Connection state is never a flag in SQLite; `GET /gmail/status` always
reflects what's actually on disk (and, when a refresh is due, what Google
itself says).

```
GET    /gmail/status                  {connected, detail?}
POST   /gmail/connect                 opens the browser; blocks until done/denied/timed out
POST   /gmail/disconnect              removes the local token (best-effort revoke at Google)
```

In chat, four tools in `services/tools/gmail.py` cover reading:

```
gmail.recent(limit?)                        most recent inbox mail, no filter
gmail.search(query, limit?)                 Gmail's own search syntax (from:, subject:, after:, is:unread, ...)
gmail.read(message_id?, query?)             one message in full, including its plain-text body
gmail.draft_reply(message_id?, query?)      retrieves the email being replied to; the reply
                                             text itself is written as the answer, shown as a
                                             draft card in the desktop app -- never sent, never
                                             saved to Gmail, only ever text in the chat
```

`gmail.search`/`gmail.recent` return metadata and a snippet only, never the
body, so a full fetch only happens when actually reading or drafting.
A query matching more than one email is never guessed at: the assistant is
told to list the candidates and ask which one. Email content -- sender,
subject, snippet, body -- is always rendered as plainly-labelled data next
to an explicit note that it must never be treated as an instruction, since
it comes from a third party, not the user (see the identity prompt in
`services/llm/prompts.py`). None of it is ever fed back into memory
extraction, tool selection, or anything else that could act on it.

## Tasks

```
GET    /tasks?filter=open             today|tomorrow|week|overdue|open|completed|cancelled|all
POST   /tasks                         {title, description?, due_at?, priority?, remind_at?}
GET    /tasks/{id}
PATCH  /tasks/{id}                    {title?, description?, due_at?, priority?, remind_at?, clear?}
POST   /tasks/{id}/complete           keeps the row, sets completed_at
POST   /tasks/{id}/cancel
POST   /tasks/{id}/reopen
```

Dates are given in **local** time (`2026-09-15T18:00:00`) and stored as UTC.
In chat, the assistant reaches the same service through five structured
tools (`tasks.list/create/update/complete/cancel`).

## Tool selection

Every chat message goes through one selection call (`services/tools/selector.py`)
that decides which tool, if any, answers it -- no keyword pre-filter in
front, so the model judges intent from the wording itself, in any language.
Execution is separate from writing the answer: a tool runs first (or the
desktop app runs it, for the two calendar ones), its result is rendered as
plain indented text in the user's own turn (never JSON, never the system
prompt), and the reply is written from that. See
[docs/architecture.md](../docs/architecture.md).

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
key (and, if connected, the Gmail credentials/token) from
`~/Library/Application Support/PersonalAIAssistant/`, not from `backend/.env`
or `backend/secrets/`. See [docs/release.md](../docs/release.md).
