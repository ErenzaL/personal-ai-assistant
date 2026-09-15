# Dully

A personal AI desktop assistant for macOS. A small floating mascot near the
bottom-right of the screen opens into a chat panel, backed by a local FastAPI
service and a SQLite database — everything runs on your own Mac.

## What Dully does

- **Chat** — streaming replies, persistent conversation history, Markdown rendering.
- **Personal memory** — learns durable facts from ordinary conversation on its own
  (an LLM decides what's worth keeping and merges updates instead of duplicating),
  retrieved by meaning rather than keyword matching, and reviewed/edited/forgotten
  from Settings. Off switch included; nothing is stored while it's off.
- **Calendar** — reads and creates events through macOS Calendar (EventKit: iCloud,
  Google, and anything else System Settings already knows about) from natural
  language. New events always show a Confirm/Edit/Cancel card first; nothing is
  written without that.
- **Gmail** — connects with Google OAuth (read-only scope), then reads, searches, and
  summarizes email, and can draft a reply shown in chat for you to copy. It never
  sends anything, never writes to your mailbox, and never creates a Gmail draft
  through the API.
- **Tasks** — a local to-do list, reachable from chat or the quick-action buttons.
- **Reminders** — a native macOS notification a few minutes before a calendar event,
  with snooze and dismiss.
- **Settings** — one compact panel for all of the above: assistant name, memory,
  calendar, Gmail, notifications, launch at login, and clearing local data.

Full-screen aware: the mascot floats above other apps' full-screen Spaces too.

## Structure

```
personal-ai-assistant/
  desktop/    Tauri 2 + React + TypeScript app (mascot, chat UI, EventKit bridge)
  backend/    Python FastAPI service (LLM, tools, SQLite, Gmail OAuth)
  scripts/    build-backend.sh, build-release.sh, set-app-icon.sh
  docs/       architecture.md, calendar-design.md, release.md
```

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together,
[docs/calendar-design.md](docs/calendar-design.md) for the EventKit integration, and
[docs/release.md](docs/release.md) for packaging and installing a build.

## Prerequisites

- Node.js 20+ and npm
- Rust toolchain (`rustup`, `cargo`)
- Xcode Command Line Tools (`xcode-select --install`)
- Python 3.11+
- A Gemini or Groq API key (for chat) — see [backend/README.md](backend/README.md)
- Optionally, a Google OAuth "Desktop app" credentials file (for Gmail) — see
  [backend/README.md](backend/README.md#gmail-setup)

## Quick start (development)

Backend:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set GEMINI_API_KEY (or GROQ_API_KEY)
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/health and expect `{"status":"ok"}`.

Desktop app, in another terminal:

```sh
cd desktop
npm install
npm run tauri dev
```

The first run compiles the Rust side and takes a few minutes. The mascot stays
hidden until the cursor touches the bottom-right edge of the screen, or use the
menu bar icon. The app has no Dock icon; quit from the menu bar icon.

Calendar and Gmail features need the app running as an installed `.app` bundle
(see below) — macOS does not grant either permission to a bare terminal-launched
process, so `tauri dev` can develop the UI but not exercise those two features.

## Production build

```sh
./scripts/build-release.sh
```

Produces `desktop/src-tauri/target/release/bundle/macos/Dully.app` and
`release/Dully.dmg`: the frontend bundled, the backend packaged into one
executable that Dully starts and stops itself, everything bound to
`127.0.0.1` only. See [docs/release.md](docs/release.md) for installing it,
where the API key and Gmail credentials go for that build, and how to update
it later.

## Status

V1 feature-complete: chat, streaming, persistence, semantic personal memory,
calendar read/write, Gmail read/search/summarize/draft, tasks, reminders,
settings, launch at login, and a packaged release build.
