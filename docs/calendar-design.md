# Calendar support: design

Status: **proposed, not implemented.** No Google OAuth, no iCloud credentials,
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
calendar_list_calendars()           -> CalendarInfo[]           (id, title, color, source, writable)
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
   A test binary linked this way contained the readable
   `NSCalendarsFullAccessUsageDescription` string in a 0x15e-byte section.
   Without this, calendar work is only testable via `tauri build`.

2. **TCC identity churn in development.** Permission is recorded against the
   bundle identifier and code signature. An unsigned dev binary changes on
   every rebuild, so approvals may be re-requested or silently denied. Expect
   to re-grant during development; reset with
   `tccutil reset Calendar com.linerenza.personal-ai-assistant`. Treat a
   bundled build as the source of truth for permission behaviour.

3. **`EKEventStore` is not thread-safe.** Keep exactly one store in Tauri
   managed state behind a `Mutex`, and never let EventKit objects cross
   threads. Fetches can be slow, so commands should be `async` and do the work
   on a blocking thread, not on the main thread and not on the event loop.

4. **The access request is a completion block.** `requestFullAccessToEvents`
   takes an Objective-C block. Bridging needs `block2::RcBlock` plus a channel
   to turn the callback into an awaitable result, with care that the block
   outlives the call and is safe to send.

5. **All-day events, timezones and recurrence.** The predicate expands
   recurring events into occurrences, and all-day events carry a floating
   timezone. Naively formatting `startDate` will produce off-by-hours and
   off-by-one-day bugs. This is the most likely source of silent wrongness and
   deserves explicit handling and tests.

6. **Unsafe code.** Every objc2 call is `unsafe`. Same discipline as
   `platform.rs`: narrow unsafe blocks with SAFETY comments explaining the
   invariant.

7. **Not every calendar is writable.** Subscribed and holiday calendars reject
   writes, and `defaultCalendarForNewEvents` can point at one. Check
   `allowsContentModifications` before saving and surface a clear error.

8. **Google calendars appear only if the account is configured in macOS.** If
   the user has not added the account in System Settings, those calendars
   simply will not exist. There is no OAuth fallback by design, so the UI
   should say this plainly rather than appear broken.

9. **Permission can be revoked at any time.** Every command must handle
   `denied` as a normal outcome, not an exception.

## F. Implementation sequence

Each step ends with `cargo check` and a manual verification before the next.

| Phase | Work | How it is verified |
|---|---|---|
| 0 | `Info.plist` + `build.rs` embedding. No EventKit yet. | `strings target/debug/desktop \| grep NSCalendarsFullAccess` finds it; the app still runs |
| 1 | Add the dependency, module skeleton, `calendar_get_authorization_status` | returns `not_determined`, and shows **no** prompt |
| 2 | `calendar_request_access` with the block bridge | the macOS prompt appears in dev; the app is listed in System Settings → Privacy → Calendars; status becomes `full_access` |
| 3 | `calendar_list_calendars` | the returned titles match the macOS Calendar app, including any Google account |
| 4 | `calendar_list_events(start, end)` | a known week matches Calendar.app exactly, including an all-day event and a recurring one |
| 5 | `calendar_create_event`, guarded by `allowsContentModifications` and an explicit user confirmation | the event appears in Calendar.app and syncs to the provider |
| 6 | `services/calendar.ts` + types, and a small Settings section showing status and a Grant access button | works end to end from the UI |

**Phase 7 is a separate decision, not part of this bridge.** The assistant's
tools live in FastAPI, but calendar access lives in Tauri, so the backend
cannot read the calendar directly. The clean resolution is frontend-executed
tools: the backend's selector returns a calendar tool call, the frontend runs
it natively and posts the structured result back, and the backend then writes
the answer from that result. That keeps the constraint intact, since FastAPI
only ever sees event data the app chose to send and never any credential.
Worth agreeing on before phase 6.
