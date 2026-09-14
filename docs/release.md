# Dully — building and installing the personal release

## Runtime architecture

```
Dully.app  (Tauri, Rust + React, ad-hoc signed)
├── Contents/MacOS/Dully           the app: mascot window, chat UI, EventKit bridge,
│                                  reminder thread, backend launcher, tray, login item
└── Contents/MacOS/dully-backend   the packaged FastAPI backend (PyInstaller, one file)
        ↑ started by the app on the first free port from 8000, 127.0.0.1 only
        ↓ stops when the app quits; exits by itself if the app disappears

~/Library/Application Support/PersonalAIAssistant/      backend data
    assistant.db      conversations, messages, memories, settings, tasks,
                      notification history (SQLite, WAL)
    .env              the LLM API key, user-only permissions (0600)
~/Library/Application Support/com.linerenza.personal-ai-assistant/   app data
    reminders.json    reminder state         backend.log   last backend run
```

The webview asks the app for the backend's URL at startup, so a port change
is invisible. The model is only ever called by the backend, with the key
read from the `.env` in the data folder; the frontend has no key and no
model code. Calendar and login-item state come from macOS and are never
stored.

## Backend packaging

`scripts/build-backend.sh` runs PyInstaller from `backend/.venv` and writes
`desktop/src-tauri/binaries/dully-backend-<target>`. The Tauri production
config (`desktop/src-tauri/tauri.prod.conf.json`) declares it as an external
binary, so `tauri build` copies it into the bundle. Nothing from
`backend/.env` is included. Development builds do not use it: `tauri dev`
starts the backend from the source folder's virtualenv (or reuses a running
`--reload` server).

## Build

```sh
./scripts/build-release.sh
```

Produces:

- `desktop/src-tauri/target/release/bundle/macos/Dully.app`
- `release/Dully.dmg`

The script packages the backend, runs `npm run tauri build -- --bundles app
--config src-tauri/tauri.prod.conf.json`, ad-hoc signs the app (which binds
the Info.plist so macOS will show the calendar prompt), and makes the DMG.

## Install

1. Open `release/Dully.dmg` and drag Dully to Applications, or copy the
   `.app` there.
2. Put the API key where the packaged backend reads it, once:

   ```sh
   mkdir -p ~/Library/Application\ Support/PersonalAIAssistant
   printf 'GEMINI_API_KEY=your-key\n' > ~/Library/Application\ Support/PersonalAIAssistant/.env
   chmod 600 ~/Library/Application\ Support/PersonalAIAssistant/.env
   ```

3. Open Dully. Allow calendar access when macOS asks. Turn on "Launch at
   login" in Settings if wanted (off by default).

Existing development data is used as-is: the database path did not change.

## Gatekeeper

A build made on this Mac carries no quarantine flag, so it opens without any
prompt. If the `.app` or `.dmg` is copied to another Mac (AirDrop, download),
macOS marks it and refuses an unsigned app once: open System Settings >
Privacy & Security and choose "Open Anyway", or clear the flag with
`xattr -dr com.apple.quarantine /Applications/Dully.app`. Because the
signature is ad-hoc, every rebuild is a new identity to macOS: calendar
access and the login item are asked again after each update. A self-signed
certificate in Keychain Access, used with `codesign -s`, would make them
stick; not set up in V1.

## Update

```sh
./scripts/build-release.sh
quit Dully (menu bar icon)
rm -rf /Applications/Dully.app && ditto desktop/src-tauri/target/release/bundle/macos/Dully.app /Applications/Dully.app
open /Applications/Dully.app
```
