# Calendar support: design

Status: **phases 0-5 and 7 implemented**: usage description, event store,
authorization, listing calendars, reading events, creating events behind an
in-chat confirmation, and the client-executed calendar tools. No Google OAuth, no iCloud credentials,
no Apple secrets anywhere. Calendars come from the macOS Calendar database,
which already aggregates whatever the user configured in System Settings
(iCloud, Google, Exchange, subscribed feeds).

## A. Recommended architecture

Call EventKit directly from Rust with the `objc2-event-kit` bindings, as a
`calendar` module inside the existing `src-tauri` crate, exposed as ordinary
Tauri commands.

```
React  (src/services/calendar.ts)
  ↓  invoke()
Tauri commands  (src-tauri/src/calendar/commands.rs)
  ↓
EventKit bridge  (src-tauri/src/calendar/eventkit.rs, objc2-event-kit)
  ↓
macOS Calendar database
  ↓
iCloud / Google / Exchange / subscribed calendars
```

FastAPI is not on this path.

No separate Swift binary, no Objective-C shim, no plugin crate.

## B. Why this and not the alternatives

The deciding factor is that **this project already calls AppKit from Rust
through objc2**. `src-tauri/src/platform.rs` uses `objc2-app-kit` for
`NSWorkspace`, `NSWindow` collection behaviour and the activation policy. The
crate family and the unsafe discipline are already established here, so
EventKit is a continuation, not a new mechanism.

Verified facts behind the choice:

| Check | Result |
|---|---|
| `objc2-event-kit` exists | yes, `0.3.2` |
| Version match with the tree | exact: `objc2-app-kit 0.3.2`, `objc2-foundation 0.3.2`, `objc2 0.6.4` |
| Required APIs present | `authorizationStatusForEntityType`, `requestFullAccessToEventsWithCompletion`, `calendarsForEntityType`, `predicateForEventsWithStartDate_endDate_calendars`, `eventsMatchingPredicate`, `saveEvent_span_error`, `defaultCalendarForNewEvents` |
| New build tooling needed | none; `cargo build` covers it |

**Swift helper (sidecar).** Best EventKit ergonomics, worst everything else.
It needs `swiftc` in every build and CI, a sidecar named per target triple,
an `externalBin` entry, its own signing and notarization, and — the real
problem — its own embedded usage description, because TCC attributes calendar
access to the binary that asks. A helper tends to show up in System Settings →
Privacy → Calendars as a second, confusingly named entry, and permission
granted to the app does not transfer to it. Rejected.

**Objective-C shim via the `cc` crate.** Workable, and blocks are pleasant in
ObjC. But it means hand-written `extern "C"` FFI and a third language in the
repo, to reach APIs for which generated bindings already exist. Rejected as
strictly more work than option A for the same result.

**Custom Tauri plugin.** A plugin is a packaging convention around the same
code. It buys per-command capability gating and reuse across apps, neither of
which this app needs today. The module below is self-contained enough to be
lifted into a plugin later if that changes. Rejected as premature.

**Third-party wrapper crates** (e.g. `highlandcows-eventkit`). Extra trust
surface and unknown maintenance for a thin convenience layer. Rejected.

## C. Required source files

Native, all under `desktop/src-tauri/`:

| File | Purpose |
|---|---|
| `Cargo.toml` | add `objc2-event-kit` (features `EKEventStore`, `EKEvent`, `EKCalendar`, `EKCalendarItem`, `EKObject`, `EKTypes`, `EKSource`, `EKAlarm`) and `block2` for the completion handler |
| `Info.plist` | usage descriptions (see D); Tauri merges this at bundle time |
| `build.rs` | embed `Info.plist` into the binary at link time so `tauri dev` works (see E, risk 1) |
| `src/calendar/mod.rs` | module root, re-exports |
| `src/calendar/types.rs` | serde DTOs: `AuthorizationStatus`, `CalendarInfo`, `CalendarEvent`, `NewEvent` |
| `src/calendar/eventkit.rs` | the unsafe bridge: store handling, status, access request, fetch, save |
| `src/calendar/commands.rs` | the five `#[tauri::command]` functions |
| `src/lib.rs` | register the commands, hold the `EKEventStore` in managed state |

Frontend:

| File | Purpose |
|---|---|
| `desktop/src/types/calendar.ts` | types mirroring the Rust DTOs |
| `desktop/src/services/calendar.ts` | typed `invoke()` wrappers, same shape as `services/mascotWindow.ts` |

**No capability changes.** App-defined commands need no entry in
`capabilities/default.json`; only core Tauri commands do. This was already
established by `set_chat_open`.

Command surface:

```
calendar_get_authorization_status() -> "not_determined" | "restricted" | "denied" | "full_access" | "write_only"
calendar_request_access()           -> AuthorizationStatus      (async, shows the macOS prompt)
calendar_list_calendars()           -> CalendarInfo[]           (id, title, source_name, source_type,
                                                               allows_modifications, color, is_default)
calendar_list_events(start, end, calendar_ids?) -> CalendarEvent[]
calendar_create_event(NewEvent)     -> CalendarEvent
```

## D. Entitlements and Info.plist

**Info.plist** — required. macOS 14+ demands the full-access key for read and
write; the legacy key is harmless and covers older systems.

```xml
<key>NSCalendarsFullAccessUsageDescription</key>
<string>Your assistant reads and adds events in your calendars so it can answer
questions about your schedule.</string>

<key>NSCalendarsUsageDescription</key>
<string>Your assistant reads and adds events in your calendars so it can answer
questions about your schedule.</string>
```

**Entitlements** — none needed. There is no entitlements file today and
`tauri.conf.json` sets no `bundle.macOS.entitlements`, so the app is **not
sandboxed**. An unsandboxed app needs only the usage description; TCC handles
the rest. Hardened runtime, which Tauri applies for notarization, does not
require a calendar entitlement.

Only if the app is later sandboxed for the Mac App Store would it need:

```xml
<key>com.apple.security.app-sandbox</key><true/>
<key>com.apple.security.personal-information.calendars</key><true/>
```

Note in passing: `macOSPrivateApi: true` is already enabled for the
transparent mascot window, and that alone bars Mac App Store distribution. So
sandboxing is not a near-term concern, and direct distribution (signed +
notarized) is the assumed path.

## E. Risks

1. **`tauri dev` has no Info.plist.** Confirmed by inspection: `tauri-build`
   only emits `rerun-if-changed` for `Info.plist`, it never embeds it, the dev
   binary has no `__TEXT,__info_plist` section, and `tauri dev` runs a bare
   executable rather than a `.app`. Calling EventKit without a usage
   description terminates the process with a TCC violation.
   **Mitigation, verified working:** in `build.rs`, embed the plist at link
   time.
   ```rust
   println!("cargo:rustc-link-arg=-Wl,-sectcreate,__TEXT,__info_plist,{path}");
   ```
   **Embedding alone is not enough.** rustc leaves a *linker-signed* ad-hoc
   signature that does not bind the plist: `codesign -dv` reports
   `Info.plist=not bound`, and TCC ignores an unbound usage description. The
   symptom is the worst kind: pressing the button does nothing at all, with no
   prompt and no error, because the request fails silently.
   The binary must be **re-signed after linking**, which binds the plist
   (`codesign -dv` then reports `Info.plist entries=2`). `tauri dev` runs
   `cargo run`, so a cargo runner does this on every launch:
   `.cargo/config.toml` points `target.'cfg(target_os = "macos")'.runner` at
   `scripts/dev-sign-run.sh`, which re-signs ad-hoc with a stable
   `--identifier` and then execs the binary. Verified: fresh build reports
   `not bound`, and after the runner reports `entries=2`.

2. **`tauri dev` cannot obtain calendar permission at all.** This is the
   decisive constraint, found by experiment rather than documentation. macOS
   attributes a privacy request to the *responsible process*, which for a
   binary started from a terminal is the terminal, not the app. EventKit then
   declines immediately: the completion handler reports `granted=false` with
   **no error and no prompt**, and `tccd` logs nothing at all. Measured with
   the same test binary:

   | How it was started | bundleIdentifier | Result |
   |---|---|---|
   | bare binary from a shell | `None` | `granted=false`, no prompt |
   | inside a `.app`, exec'd from a shell | set | `granted=false`, no prompt |
   | inside a `.app`, launched by LaunchServices (`open`) | set | **`granted=true`** |

   Wrapping the dev binary in a bundle and launching it with `open` from the
   cargo runner does work when run by hand, but fails with LaunchServices
   error `-10810` inside npm's process tree, so it is not a reliable dev
   workflow. **Calendar permission is therefore granted from a built bundle**
   (`npm run tauri build -- --debug --bundles app`, then `codesign --force
   --deep --sign -` on the result because Tauri leaves it unsigned). In
   `tauri dev` the request returns the `prompt_unavailable` error, and the
   Settings panel explains what to do instead of failing silently.

3. **TCC identity churn in development.** Permission is recorded against the
   code signature. There is no Developer ID on this machine
   (`security find-identity` finds none), so dev builds are ad-hoc signed and
   their cdhash changes on every rebuild: expect macOS to ask again after
   code changes. A bundled, properly signed build is the stable experience. Expect
   to re-grant during development; reset with
   `tccutil reset Calendar com.linerenza.personal-ai-assistant`. Treat a
   bundled build as the source of truth for permission behaviour.

4. **`EKEventStore` is not thread-safe.** Keep exactly one store in Tauri
   managed state behind a `Mutex`, and never let EventKit objects cross
   threads. Fetches can be slow, so commands should be `async` and do the work
   on a blocking thread, not on the main thread and not on the event loop.

5. **The access request is a completion block.** `requestFullAccessToEvents`
   takes an Objective-C block. Bridging needs `block2::RcBlock` plus a channel
   to turn the callback into an awaitable result, with care that the block
   outlives the call and is safe to send.

6. **All-day events, timezones and recurrence.** The predicate expands
   recurring events into occurrences, and all-day events carry a floating
   timezone. Naively formatting `startDate` will produce off-by-hours and
   off-by-one-day bugs. This is the most likely source of silent wrongness and
   deserves explicit handling and tests.

7. **Unsafe code.** Every objc2 call is `unsafe`. Same discipline as
   `platform.rs`: narrow unsafe blocks with SAFETY comments explaining the
   invariant.

8. **Not every calendar is writable.** Subscribed and holiday calendars reject
   writes, and `defaultCalendarForNewEvents` can point at one. Check
   `allowsContentModifications` before saving and surface a clear error.

9. **Google calendars appear only if the account is configured in macOS.** If
   the user has not added the account in System Settings, those calendars
   simply will not exist. There is no OAuth fallback by design, so the UI
   should say this plainly rather than appear broken.

10. **Permission can be revoked at any time.** Every command must handle
   `denied` as a normal outcome, not an exception.

## F. Implementation sequence

Each step ends with `cargo check` and a manual verification before the next.

| Phase | Work | How it is verified |
|---|---|---|
| 0 | ~~`Info.plist` + `build.rs` embedding. No EventKit yet.~~ **done** | embedded section is a valid plist; `plutil -extract` returns the usage string |
| 1 | ~~Add the dependency, module skeleton, `calendar_get_authorization_status`~~ **done** | returns `not_determined` with no prompt; EventKit reachable, store creates cleanly |
| 2 | ~~`calendar_request_access` with the block bridge~~ **done** | app boots with the `eventkit` worker thread alive, no TCC crash; awaiting a real Allow click |
| 3 | ~~`calendar_list_calendars`~~ **done** | verified against a live account: iCloud, Google, subscribed and Birthdays calendars all returned |
| 4 | ~~`calendar_list_events(start, end)`~~ **done** | verified end to end: bounds resolved correctly, empty ranges reported as empty |
| 5 | ~~`calendar_create_event`, guarded by `allowsContentModifications` and an explicit user confirmation~~ **done** | proposal card with Confirm/Edit/Cancel; only Confirm writes |
| 6 | `services/calendar.ts` + types, and a small Settings section showing status and a Grant access button | works end to end from the UI |

**Phase 7 is now implemented.** The assistant's
tools live in FastAPI, but calendar access lives in Tauri, so the backend
cannot read the calendar directly. The clean resolution is frontend-executed
tools: the backend's selector returns a calendar tool call, the frontend runs
it natively and posts the structured result back, and the backend then writes
the answer from that result. That keeps the constraint intact, since FastAPI
only ever sees event data the app chose to send and never any credential.
Worth agreeing on before phase 6.

## G. Provider reporting

Requirement: never invent a provider. `source_name` is EventKit's own source
title, which is exactly what the macOS Calendar app shows as a sidebar
heading, and `source_type` is EventKit's `EKSourceType` mapped one-to-one. A
Google calendar is reported as `cal_dav` with `source_name: "Google"` because
that is what macOS says, not because anything inferred it. If EventKit
returns a source type this build does not recognise, `source_type` is null
rather than guessed.

Note that iCloud and Google both surface as `cal_dav`, which is why the
*name* rather than the *type* is what distinguishes accounts.

The user's chosen default calendar is stored as `default_calendar_id` among
the ordinary app preferences. That is an opaque identifier, not calendar
data, so it does not breach the "calendar access never goes through FastAPI"
rule. When it is unset the app falls back to EventKit's
`defaultCalendarForNewEvents`.

A support diagnostic is built in: running the bundled app with
`--list-calendars` requests access if needed, prints this JSON, and exits.

## H. The client-executed tool bridge (phase 7)

The assistant's tools live in FastAPI, but calendar access lives in Tauri, so
the backend cannot read a calendar. Resolved with a one-round-trip protocol:

1. `POST /chat/stream` -- the selector picks `calendar.read`. The backend sees
   `execution: CLIENT`, validates the arguments, and emits
   `event: client_tool {name, arguments}` instead of an answer. Nothing is
   saved and no assistant message exists yet.
2. The desktop app runs it natively (`services/clientTools.ts` ->
   `calendar_list_events`) and wraps the outcome in the same
   `{ok, tool, data|error}` envelope the backend uses.
3. It posts `/chat/stream` again with the original `user_message_id` plus
   `tool_results`. The backend skips selection, renders the result into local
   wording (`tools/calendar.py: summarise`), puts it in the "Results for this
   message" section, and streams the reply.

The frontend allows exactly one round trip, so this cannot loop. FastAPI only
ever sees the event data the app chose to send, never a credential, which is
what keeps the "calendar access never goes through FastAPI" rule intact.

## I. Creating events from chat

Two tools, both client-executed:

| Tool | What it does |
|---|---|
| `calendar.read(start, end)` | reads events for a range |
| `calendar.propose_event(title, start, end?, duration_minutes?, calendar_name?, location?, notes?)` | prepares an event; **creates nothing** |

The model only supplies words. Everything that has to be exact is computed in
`services/eventPlanning.ts`:

- **End time.** `end` if given, else `start + duration_minutes`, else
  `start + 60`. Computed with real date arithmetic, so it is correct across
  midnight and DST, and never left to the model.
- **Calendar.** A name the user said, then the configured
  `default_calendar_id`, then the calendar macOS uses for new events, then the
  first writable one. Read-only calendars (holidays, subscriptions) are never
  chosen.
- **Conflicts.** Existing events in the same window that genuinely overlap.
  All-day entries never count, and touching edges (10:00-11:00 vs 11:00-12:00)
  are not a clash. A conflict is a warning; it never blocks.

The proposal is posted back so the assistant introduces it in its own words,
which keeps the conversation history well formed, and the card renders under
that message. `calendar_create_event` is reachable only from the Confirm
button.

**A bug worth recording:** the first version ended the turn without saving any
assistant message. The stored history then became a run of consecutive user
turns, and the selector started answering the *first* one for every later
message. Any flow that consumes a user message must leave an assistant message
behind.
