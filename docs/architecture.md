# Architecture

## Overview

Two processes:

| Layer    | Tech                          | Location    |
|----------|-------------------------------|-------------|
| Desktop  | Tauri 2 + React + TypeScript  | `desktop/`  |
| Backend  | Python FastAPI + SQLite       | `backend/`  |

The desktop app is the only user-facing surface. The backend runs locally and owns
persistence, calendar integration, and LLM calls. The two communicate over HTTP on
localhost: the frontend calls `GET /health` when the chat opens and `POST /chat`
for each message with the recent turns as context; `POST /chat` answers via the
configured LLM provider.

## Desktop `src/` layout

| Folder        | Purpose                                              |
|---------------|------------------------------------------------------|
| `components/` | React UI components (mascot, chat, panels)           |
| `services/`   | API clients and Tauri command wrappers               |
| `hooks/`      | Reusable React hooks                                 |
| `stores/`     | Client-side state                                    |
| `types/`      | Shared TypeScript types                              |
| `assets/`     | Static files bundled with the app (mascot PNG, etc.) |

Rust code lives in `desktop/src-tauri/`. Keep it thin: window management and
OS integration only.

## Mascot window

The main window is a small (170x170), frameless, transparent, always-on-top
window that rests at the bottom-right of the current monitor's work area
(80 px from the right edge, directly above the Dock).

| Piece                                  | Role                                                        |
|----------------------------------------|-------------------------------------------------------------|
| `src-tauri/tauri.conf.json`            | Window flags (transparent, no decorations, always on top)   |
| `src-tauri/Cargo.toml`                 | `macos-private-api` feature, required for transparency      |
| `src-tauri/src/mascot_window.rs`       | Resting position (bottom-right); cursor-over hit test       |
| `src-tauri/src/platform.rs`            | macOS-only: frontmost app pid; float over full-screen Spaces |
| `src-tauri/src/tray.rs`                | Menu bar icon with Show / Quit (app has no Dock icon)       |
| `src-tauri/src/activation.rs`          | Edge-activation poller and visibility state machine         |
| `src-tauri/capabilities/default.json`  | Grants `core:window:allow-start-dragging` for drag-to-move  |
| `src/components/Avatar/`               | Generic image component with hover lift (`src`, `alt`, `size`) |
| `src/components/MascotStage/`          | Translucent grey platform, shorter than the avatar, that it stands on |
| `src/assets/assistant.png`             | Current mascot image; swap the import in `App.tsx` to replace |
| `src/styles.css`                       | Column layout: optional chat panel over a fixed mascot box  |
| `src/components/Chat/`                 | ChatWindow (holds both views), ChatHeader, MessageList, MessageBubble, ChatInput, QuickActions |
| `src/components/Settings/`             | SettingsPanel, MemorySection, AssistantSection              |
| `src/hooks/useMemories.ts`             | Active memories; add / edit / forget through the backend    |
| `src/hooks/useSettings.ts`             | Assistant name and response style                           |
| `src/hooks/useChat.ts`                 | Loads/persists the current conversation via the backend; streaming, retry, new chat |
| `src/services/api.ts`                  | Typed HTTP client (timeouts, `ApiError` kinds), all endpoints |
| `src/config.ts`                        | `API_BASE_URL` from `VITE_API_BASE_URL` in `.env.development.local` / `.env.production` (files only; shell vars are not read) |
| `src/stores/chatSeed.ts`               | Assistant name, greeting, quick-action prompts              |
| `src/services/mascotWindow.ts`         | Wraps the `set_chat_open` Tauri command                     |
| `src-tauri/src/commands.rs`            | `set_chat_open`: resize, re-anchor, focusable, pin visible  |

Platform height, color, and the avatar's inset are CSS variables at the top of
`MascotStage.css`. Avatar size is the `size` prop in `App.tsx`.

### Edge activation

The window starts hidden and is `focusable: false`, so showing it never steals
keyboard focus from the app in front. A background thread in `activation.rs`
polls the global cursor every 80 ms via `AppHandle::cursor_position` (on macOS
this is `NSEvent.mouseLocation`; no Accessibility permission is needed).

States: `Hidden` -> cursor in the bottom 12 px strip of the primary display
(right part only, from 60 px left of the mascot to the screen edge) ->
`Visible` -> cursor leaves strip and mascot -> `Leaving` (3 s timer) -> `Hidden`.
If a different app becomes frontmost while the mascot is showing, it hides
immediately. A 16 px slack around the window and the 3 s delay prevent flicker
while moving between the strip and the mascot. `VisibilityFlags::chat_open` (Tauri managed
state) pins the window visible; nothing sets it yet.

Tunables are the constants at the top of `activation.rs`.

### Full-screen Spaces and accessory mode

The mascot also appears over other apps' full-screen Spaces. Two things are
required, both verified empirically on macOS 26:

1. The window carries `CanJoinAllSpaces | FullScreenAuxiliary` at status-window
   level (`platform::allow_over_fullscreen`).
2. The app runs with the *accessory* activation policy, applied in two places
   in `lib.rs`: directly on `NSApplication` before Tauri builds the window
   (`platform::become_accessory_app`), and on the Tauri `App` before `run()`
   so the event loop does not reset it to Regular at launch. Both matter:
   macOS fixes a window's Space eligibility at creation, and a window created
   while the app is Regular is excluded from full-screen Spaces for good, even
   if the policy changes later. Tauri runs the `setup` hook after launch, so
   setting the policy there is too late.

Accessory mode means no Dock icon and no menu bar, so `tray.rs` adds a menu bar
icon with "Show assistant" and "Quit". During `tauri dev`, Ctrl+C in the
terminal also quits. A side effect: activating the app (focusing the chat input)
no longer switches Spaces, so chat works inside full-screen apps too.

Set `MASCOT_DEBUG=1` before `npm run tauri dev` to log the poller's state
transitions and the live window's level/behavior to the terminal.

### Chat panel

One window, two sizes. Clicking the mascot invokes `set_chat_open(true)`: the
Rust side flags `chat_open`, resizes the window from 170x170 to 420x740 while
keeping the bottom-right corner fixed, and makes the window focusable so the
text input receives keys. React then renders `ChatWindow` above the mascot box.
Close (button, Esc, or clicking the mascot) reverses all of it. Sizes live in
`MASCOT_SIZE` / `CHAT_SIZE` in `mascot_window.rs` and `--mascot-box` in
`styles.css`; keep them in sync.

Preview the panel without Tauri: `npm run dev`, then open
`http://localhost:1420/?chat` in a browser.

## Backend `app/` layout

| Folder / file | Purpose                                              |
|---------------|------------------------------------------------------|
| `main.py`     | FastAPI app, CORS middleware, router registration    |
| `config.py`   | Settings from env / `.env`; the only place keys live |
| `api/`        | HTTP routers, one per resource (`health.py`, `chat.py`) |
| `services/chat.py` | `ConversationService` (persistence, `begin_turn`) and `ChatService` (LLM call) |
| `services/context.py` | `PromptContext`: instructions / memory / history / tool results / user message |
| `services/retrieval.py` | Which stored memories (if any) enter a turn's prompt |
| `services/preferences.py` | Assistant name and response style (rows in `settings`) |
| `services/tasks.py` | `TaskService`: create / list / update / complete / cancel, with validation |
| `services/tools/` | Structured tools: registry + validation (`base.py`), task tools (`tasks.py`), selection (`selector.py`) |
| `services/timeutil.py` | Local time in, UTC on disk; day and week windows |
| `services/llm/`    | `LLMService` interface, error kinds, providers (`gemini.py`, `groq.py`), factory |
| `database/`   | SQLite: `paths.py` (app-data location), `connection.py` (connect, `get_db`, init), `migrations.py` + `migrations/*.sql`, `models.py`, `repositories/` (all SQL) |

### Data layer

SQLite via the standard library, no ORM. The file lives in the per-user
app-data folder (`~/Library/Application Support/PersonalAIAssistant/assistant.db`
on macOS; `DATABASE_PATH` overrides). `init_database` runs at startup: creates
the folder and file, enables WAL, and applies any unapplied
`migrations/NNN_*.sql` in order, recording each in `schema_migrations`.

Tables: `conversations`, `messages` (cascade-deleted with their conversation),
`notes`, `tasks` (see below), `settings`
(JSON values), `notification_history` (dedupe helper `was_sent`), and, from
migration 002, `memories`. Ids are UUID hex, timestamps ISO 8601 UTC text.

### Personal memory vs conversation history

| | Conversation history | Personal memory |
|---|---|---|
| Tables | `conversations`, `messages` | `memories` |
| Holds | what was said, verbatim, per conversation | durable facts about the user, one row per `(category, key)` |
| Written by | every chat turn, automatically | explicit API calls only (no auto-remembering) |
| Lifetime | per conversation; tail is sent as context | across all conversations; deactivated, never deleted |
| Used in prompts | yes (`select_history`) | only when relevant (`services/retrieval.py`) |

**Memory commands in chat** (`services/memory_commands.py`). Explicit
"remember / recall / forget" requests are handled before normal chat, in
`api/chat.py`:

1. `screen()`: regex for memory words (remember, forget, recall, "about me",
   기억, 잊어). No match → normal chat, no extra LLM call.
2. `interpret()`: one LLM call with a JSON-only classifier prompt →
   `MemoryIntent` (intent, category, key, third-person content, keywords,
   sensitive flag). "none" → normal chat (e.g. "I can't remember that movie").
3. `MemoryCommandHandler.execute()`: deterministic. Remember → `MemoryService`
   create (same category+key → update; sensitive → refused, with a regex
   backstop). Recall → list active memories, grouped by category. Forget →
   keyword-scored candidates among active memories; exactly one (or a clear
   winner) is deactivated, several → numbered question and a pending choice
   stored in `settings` so the next reply "2" resolves it.

The reply text is composed by the handler from the actual database result,
never by the model, so "I'll remember that" only appears after the row exists.
Command replies go through the same SSE stream as one delta and are saved as
assistant messages. Ordinary conversation is never stored as memory.

`services/memory.py` (`MemoryService`) validates categories, keys
(`lower_snake_case`), sources (user/assistant/import) and confidence (0..1),
and exposes create / update / deactivate / reactivate / get / list / search.
Search is category + exact key + case-insensitive substring on key and content
(no embeddings). `repositories/memories.py` holds the SQL; `api/memories.py`
is the REST surface.

Access pattern: a route takes `db: sqlite3.Connection = Depends(get_db)` (one
connection per request, closed afterwards) and calls a repository class from
`database/repositories/`. Routes and services contain no SQL.

### Conversation persistence

`services/chat.py` has two classes. `ConversationService` (sync, DB only):
`current()` reads `settings.current_conversation_id` (creating a conversation
on first use), `start_new()`, `begin_turn()` saves the user message and builds
the LLM context, `save_assistant_message()`. `ChatService` calls the LLM.
`api/conversations.py` exposes `GET /conversations/current`, `POST
/conversations` (new + make current), `GET /conversations`, `GET
/conversations/{id}`. Chat requests carry `conversation_id` (default current)
and, on retry, `user_message_id` so the already-saved user message is reused.

Order of events for `POST /chat/stream`: user message saved → context built →
`meta {conversation_id, user_message_id}` → `delta`s → assistant message
saved → `done {assistant_message_id}`. A failed reply is never saved. The
assistant save uses a fresh connection because the request-scoped one may be
closed by then.

**Prompt / context architecture** (`services/context.py`). One assistant, one
system prompt (`services/llm/prompts.py`: identity, responsibilities, rules).
Each turn is assembled from five separate kinds of context, in this order:

| # | Kind | Source | Rendered as |
|---|------|--------|-------------|
| 1 | System instructions | `SYSTEM_PROMPT` | system message |
| 2 | Relevant personal memory | `services/retrieval.py` (see below) | system message titled "About the user (stored memory)", only when non-empty |
| 3 | Recent conversation | DB, `select_history` policy | user/assistant messages |
| 4 | Tool results | *(future: calendar/task lookups)* | system message titled "Results for this message", only when non-empty |
| 5 | Current user message | request | user message, last |

`build_context(history, user_message, memory=..., tool_results=...)` returns a
`PromptContext`; `.messages()` renders it. The identity prompt refers to the
two section titles by name and states that an absent section means "unknown"
/ "no lookup happened", which is what stops the model from pretending to
remember or to have checked something. Memory is retrieved in
`ConversationService.begin_turn` between saving the user message and calling
`build_context`; tool lookups will plug in the same way. Gemini merges all
system messages in order into its single system instruction; Groq/OpenAI-style
providers receive them as separate system messages.

### Memory retrieval

`services/retrieval.py` decides, per message, which stored memories (if any)
join the prompt. No extra LLM call and no embeddings, so an ordinary question
costs exactly what it did before.

1. **Gate** (`is_personal`): the message must refer to the user (I, my, we) or
   to arranging something (schedule, meeting, remind, tomorrow, deadline…).
   "What is Kubernetes?" fails the gate, so the database is not even read and
   no memory section is built.
2. **Score**: distinctive terms of the message against each *active* memory's
   key + content, with a crude singular form so "meetings" matches "meeting".
   A planning question qualifies a memory on one shared term; any other
   personal message needs two, so a single common word ("main", "time")
   cannot drag in an unrelated memory. Preference/routine memories rank
   higher on planning questions.
3. **Cap**: at most 3 memories and 600 characters. The whole store is never
   injected. No match means no section, and the turn proceeds normally.

Logging (`app.memory`) records the count plus each memory's short id and
category, never its content. `MemoryRetriever` is a Protocol and
`get_retriever()` the single construction point, so a semantic retriever can
replace the keyword one without touching the chat service.

History policy (`select_history`): only the current conversation; walk back
from the newest message and stop at 20 messages or 12,000 characters,
whichever comes first. Lifetime history is never sent.

Frontend: `useChat` loads the current conversation on open (so it survives an
app restart), shows the user message optimistically and swaps in the server
id from `meta`, and the "+" header button calls `POST /conversations`.

### Settings panel

One window, two views: `ChatWindow` holds `view` state and swaps the chat
transcript for `SettingsPanel`, reached from the gear in the header. Escape
leaves settings before it closes the panel, so the window never navigates
away and the mascot stays put.

**Personal memory** lists active memories as `category | wording` with Add,
Edit and Forget. Keys, ids, confidence and source stay in the service layer;
the UI shows only what a person wrote. Add posts to `POST /memories` without
a key, and the backend derives one from the content (suffixing `_2`, `_3` if
that slug is taken), so the panel never invents internal values. Forget calls
`DELETE /memories/{id}`, which deactivates. "Forget all" asks for confirmation
first and then calls `POST /memories/deactivate-all`; rows are kept either
way. Every mutation re-reads the list from the server, so the UI cannot show
a change the database refused.

**Assistant** holds the name and response style, stored in `settings` via
`services/preferences.py` and `GET`/`PATCH /settings`. Both feed
`build_system_prompt`, which appends at most two lines to the identity
prompt; with the defaults (Assistant / balanced) the prompt is byte-identical
to `SYSTEM_PROMPT`. The name saves shortly after typing stops, and
immediately on Enter or blur.

### Tasks

`tasks` (migration 003) holds `id, title, description, due_at, priority,
status, remind_at, completed_at, created_at, updated_at`. Priority is
low/normal/high and status open/completed/cancelled, both enforced by CHECK
constraints. Completing sets `completed_at` and keeps the row, so finished
work stays in history; nothing is hard-deleted by normal flows.

**Time**: every timestamp is stored as ISO 8601 UTC, so rows sort and compare
as strings, and `services/timeutil.py` is the only place local time meets
storage. "Today" and "this week" are computed from local midnight and then
converted to UTC for the query, and replies are phrased in local time
("tomorrow at 9:00 AM").

**Tools.** The task manager is exposed to the assistant as five structured
tools, and execution is deliberately separate from writing the answer:

| Stage | Where | What it does |
|-------|-------|--------------|
| screen | `tools/selector.py` | regex: could this need a tool? general questions skip everything |
| select | `tools/selector.py` | one completion -> `{"tool", "arguments"}` or `{"tool": null}`; sees the last 4 turns so "move that one to Friday" resolves |
| validate + run | `tools/base.py` | Pydantic model per tool, then the handler; never raises |
| answer | `services/chat.py` | the result JSON goes in the "Results for this message" section and the assistant writes the reply from it |

So a task request costs two completions (selection, then the streamed
answer); ordinary chat still costs one. Every call returns the same envelope,
`{"ok": true, "tool", "data"}` or `{"ok": false, "tool", "error"}`, and the
system prompt tells the assistant to read `ok` first and never describe a
failure as a success. Because the tool runs *before* the answer is written,
"I've added ..." can only appear after the row exists.

Tool signatures shown to the model are derived from the Pydantic argument
models (`ToolSpec.signature()`), so the prompt and the validation cannot
drift. Errors carry a code: `invalid_arguments`, `rejected` (the service
refused, e.g. a reminder after the due date), `not_found`, `ambiguous` (with
`candidates`, each including a `task_id` for the follow-up), `unknown_tool`,
`tool_failed`. Logging records only the tool name, ok/failed, and latency in
milliseconds, never arguments or task content.

Chat dispatch order in `api/chat.py`: memory commands (which answer directly),
then the tool phase, then answer generation. Adding a tool means one
`ToolSpec` in a registry; the provider abstraction is untouched, so native
function-calling could replace the selection step later without changing the
tools themselves.

### LLM layer

`LLMService` (`services/llm/base.py`) has two methods, `generate(messages)` and
`stream(messages)`, plus five error kinds: not configured, auth, rate limit,
network, bad response. Providers subclass `HttpLLMService`, which owns the HTTP
client, timeouts, SSE parsing, and status-to-error mapping; each provider file
only builds its request and parses its response. `factory.py` reads
`LLM_PROVIDER` and the matching key. Adding a provider means one new file and
one branch in the factory.

`POST /chat` maps error kinds to HTTP status (503 config/auth, 429 rate limit,
502 network/response) with `{"detail": {"code", "message"}}`; the frontend
shows `message` in the chat. API keys never leave the backend process.

### Streaming

`POST /chat/stream` returns Server-Sent-Events framing over a POST body
(`EventSource` is GET-only and can't carry the JSON history, so the frontend
reads the body with `fetch` + `ReadableStream`). Events: `delta {text}`,
`done {}`, `error {code, message}`. The server awaits the first token before
committing to a 200 streaming response, so bad-key and no-network failures
still come back as ordinary HTTP errors; anything that fails after that is an
in-band `error` event. Client disconnects close the generator, which closes
the upstream provider request.

Frontend (`useChat.ts`): the "..." indicator shows until the first delta; the
assistant message is created on that delta and later deltas append to it by
id. On failure the partial text stays, a system notice explains, and Retry
truncates the transcript back to the user message before re-sending, so text
is never duplicated. Closing the panel aborts the in-flight stream.
`MessageList` follows the bottom while the user is near it and stops
following if they scroll up.

The server binds to 127.0.0.1:8000. CORS allows the Tauri webview origins
(`http://localhost:1420` in dev, `tauri://localhost` when packaged) so the
frontend can call it with `fetch`.

## Roadmap

1. ~~Mascot window (transparent, always-on-top)~~ done
   ~~Edge activation (show on bottom-edge hover, auto-hide)~~ done
   ~~Chat panel UI with fake messages~~ done
2. SQLite persistence
3. Google Calendar integration
4. LLM chat
5. Notifications / reminders
