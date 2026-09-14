# Personal AI Assistant

A personal AI desktop assistant for macOS. V1 foundation.

## Structure

```
personal-ai-assistant/
  desktop/    Tauri 2 + React + TypeScript app
  backend/    Python FastAPI service
  docs/       Architecture and design notes
```

See [docs/architecture.md](docs/architecture.md) for details.

## Prerequisites

- Node.js 20+ and npm
- Rust toolchain (`rustup`, `cargo`)
- Xcode Command Line Tools (`xcode-select --install`)
- Python 3.11+

## Desktop app

```sh
cd desktop
npm install
npm run tauri dev
```

The first run compiles the Rust side and takes a few minutes. A small frameless
window with the mascot should appear near the bottom center of the screen,
floating above other windows. The app has no Dock icon; quit from the mascot
icon in the menu bar, or with Ctrl+C in the terminal.

## Backend

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/health and expect `{"status":"ok"}`.

## Status

Project foundation and floating mascot window. No AI, database, calendar, or notification code yet.
