//! Edge activation: show the mascot when the cursor touches the bottom-right
//! edge of the primary display, hide it again a few seconds after the cursor
//! leaves, or immediately when the user switches to another app.
//!
//! Implemented as a single background thread that polls the global cursor
//! position through Tauri (`AppHandle::cursor_position`). On macOS this reads
//! `NSEvent.mouseLocation`, which works without Accessibility permission.

use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

/// Set `MASCOT_DEBUG=1` in the environment to print what the poller sees to
/// stderr (state changes, plus a sample of the inputs once per second).
fn debug_enabled() -> bool {
    std::env::var_os("MASCOT_DEBUG").is_some()
}

macro_rules! debug_log {
    ($($arg:tt)*) => {
        if debug_enabled() {
            eprintln!("[activation] {}", format!($($arg)*));
        }
    };
}

use tauri::{AppHandle, Manager, PhysicalPosition, WebviewWindow};

use crate::{mascot_window, platform};

/// Height of the strip along the bottom edge of the primary display that reveals
/// the mascot, in logical pixels (scaled for Retina automatically).
const TRIGGER_HEIGHT: f64 = 12.0;

/// How far left of the mascot's resting position the trigger strip extends, in
/// logical pixels. The strip runs from there to the right edge of the screen, so
/// the cursor only needs to reach the bottom edge near where the mascot lives.
const TRIGGER_LEFT_SLACK: f64 = 60.0;

/// How long the cursor may be away from both the trigger strip and the mascot
/// before the mascot is hidden.
const HIDE_DELAY: Duration = Duration::from_secs(3);

/// Polling interval. 80 ms is fast enough to feel instant and cheap enough to
/// be invisible in Activity Monitor.
const POLL_INTERVAL: Duration = Duration::from_millis(80);
/// Tick while hidden with edge activation switched off: nothing to watch for
/// except a tray click, which a slower tick still answers promptly.
const IDLE_POLL_INTERVAL: Duration = Duration::from_millis(400);

/// Extra margin around the mascot window that still counts as "over the mascot",
/// in logical pixels. Absorbs the gap between the trigger strip and the window
/// so a cursor moving from one to the other never starts the hide timer.
const HOVER_SLACK: f64 = 16.0;

/// Shared flags other parts of the app can flip to influence visibility.
/// Managed as Tauri state so a future chat feature can set `chat_open`.
pub struct VisibilityFlags {
    /// While true the mascot never auto-hides. Set by the `set_chat_open`
    /// command while the chat panel is open.
    pub chat_open: AtomicBool,
    /// One-shot request to show the mascot (e.g. from the tray menu). The
    /// poller consumes it on the next tick and treats it like an edge trigger.
    pub show_requested: AtomicBool,
    /// While true a reminder popup is showing, which pins the window like an
    /// open chat does. Set by the reminder service, cleared by snooze/dismiss.
    pub reminder_open: AtomicBool,
    /// Whether the bottom-right edge reveals the mascot at all. Off means
    /// only the tray menu and reminders show it. Pushed from the stored settings.
    pub edge_enabled: AtomicBool,
}

impl Default for VisibilityFlags {
    fn default() -> Self {
        Self {
            chat_open: AtomicBool::new(false),
            show_requested: AtomicBool::new(false),
            reminder_open: AtomicBool::new(false),
            edge_enabled: AtomicBool::new(true),
        }
    }
}

/// Visibility state machine. Only the polling thread reads or writes it.
enum Visibility {
    /// Window is hidden. Waiting for the cursor to enter the trigger strip.
    Hidden,
    /// Window is shown and the cursor is over it or in the trigger strip.
    /// `front_app` is the app that was frontmost when the mascot appeared.
    Visible { front_app: Option<i32> },
    /// Window is shown, cursor has left. Hide when `since + HIDE_DELAY` passes,
    /// unless the cursor comes back first.
    Leaving { since: Instant, front_app: Option<i32> },
}

impl Visibility {
    fn name(&self) -> &'static str {
        match self {
            Visibility::Hidden => "Hidden",
            Visibility::Visible { .. } => "Visible",
            Visibility::Leaving { .. } => "Leaving",
        }
    }
}

/// Spawn the polling thread. Call once from `setup`, after the window exists.
pub fn start(app: AppHandle) {
    app.manage(VisibilityFlags::default());
    thread::spawn(move || poll_loop(app));
}

fn poll_loop(app: AppHandle) {
    let window = match app.get_webview_window("main") {
        Some(window) => window,
        None => return,
    };
    let flags = app.state::<VisibilityFlags>();
    let own_pid = std::process::id() as i32;
    let mut state = Visibility::Hidden;
    let mut last_sample = Instant::now();
    debug_log!("poller started (pid {own_pid})");

    loop {
        let idle = matches!(state, Visibility::Hidden) && !flags.edge_enabled.load(Ordering::Relaxed);
        thread::sleep(if idle { IDLE_POLL_INTERVAL } else { POLL_INTERVAL });

        let cursor = match app.cursor_position() {
            Ok(cursor) => cursor,
            Err(err) => {
                debug_log!("cursor_position failed: {err}");
                continue;
            }
        };
        let in_trigger =
            flags.edge_enabled.load(Ordering::Relaxed) && in_trigger_strip(&app, &window, cursor);
        let over_mascot = mascot_window::is_cursor_over(&window, cursor, HOVER_SLACK);
        let chat_open = flags.chat_open.load(Ordering::Relaxed)
            || flags.reminder_open.load(Ordering::Relaxed);
        let show_requested = flags.show_requested.swap(false, Ordering::Relaxed);
        // The mascot window is non-focusable, so it never becomes frontmost
        // itself. Treat our own pid (e.g. Dock icon clicked) as "no change".
        let front_now = platform::frontmost_app_pid().filter(|pid| *pid != own_pid);

        if debug_enabled() && last_sample.elapsed() >= Duration::from_secs(1) {
            last_sample = Instant::now();
            debug_log!(
                "state={} cursor=({:.0},{:.0}) in_trigger={in_trigger} over_mascot={over_mascot} chat_open={chat_open} front={front_now:?} visible={:?}",
                state.name(),
                cursor.x,
                cursor.y,
                window.is_visible()
            );
        }

        // --- Visibility logic ---------------------------------------------
        // Hidden   --cursor in strip / show requested-> Visible (window shown)
        // Visible  --cursor leaves strip+mascot-->      Leaving (timer starts)
        // Leaving  --cursor returns-->                  Visible (timer cancelled)
        // Leaving  --3 s elapsed-->                     Hidden  (window hidden)
        // Visible/Leaving --frontmost app changed-->    Hidden  (immediately)
        // Chat open pins the window visible: no timer, no app-switch hiding.
        state = match state {
            Visibility::Hidden => {
                if in_trigger || show_requested {
                    debug_log!("Hidden -> Visible (trigger={in_trigger} requested={show_requested})");
                    show(&window);
                    Visibility::Visible {
                        front_app: front_now,
                    }
                } else {
                    Visibility::Hidden
                }
            }
            Visibility::Visible { front_app } => {
                if chat_open {
                    Visibility::Visible { front_app }
                } else if app_switched(front_app, front_now) {
                    debug_log!("Visible -> Hidden (app switched {front_app:?} -> {front_now:?})");
                    hide(&window);
                    Visibility::Hidden
                } else if in_trigger || over_mascot {
                    Visibility::Visible { front_app }
                } else {
                    debug_log!("Visible -> Leaving (cursor left)");
                    Visibility::Leaving {
                        since: Instant::now(),
                        front_app,
                    }
                }
            }
            Visibility::Leaving { since, front_app } => {
                if chat_open || in_trigger || over_mascot {
                    // Cursor came back (or chat opened) before the delay ran out.
                    Visibility::Visible { front_app }
                } else if app_switched(front_app, front_now) || since.elapsed() >= HIDE_DELAY {
                    debug_log!("Leaving -> Hidden (timer or app switch)");
                    hide(&window);
                    Visibility::Hidden
                } else {
                    Visibility::Leaving { since, front_app }
                }
            }
        };
    }
}

/// True when a different app has come to the front since the mascot appeared.
/// Unknown pids (None) never count as a switch.
fn app_switched(at_show: Option<i32>, now: Option<i32>) -> bool {
    matches!((at_show, now), (Some(a), Some(b)) if a != b)
}

/// Re-anchor to the resting spot each time we show, in case the display layout
/// or Dock size changed while hidden, or the user dragged the window last time.
fn show(window: &WebviewWindow) {
    if let Err(err) = mascot_window::place_at_rest(window) {
        debug_log!("place_at_rest failed: {err}");
    }
    if let Err(err) = window.show() {
        debug_log!("show failed: {err}");
    }
    debug_log!("after show: {}", platform::describe_window(window));
}

fn hide(window: &WebviewWindow) {
    let _ = window.hide();
}

/// True when the cursor is within `TRIGGER_HEIGHT` of the bottom edge of the
/// primary display (the physical screen edge, so it sits under the Dock) and
/// horizontally between the mascot's resting spot (minus slack) and the right
/// screen edge.
fn in_trigger_strip(app: &AppHandle, window: &WebviewWindow, cursor: PhysicalPosition<f64>) -> bool {
    let monitor = match app.primary_monitor() {
        Ok(Some(monitor)) => monitor,
        other => {
            debug_log!("primary_monitor unavailable: {other:?}");
            return false;
        }
    };
    let origin = monitor.position();
    let size = monitor.size();
    let scale = monitor.scale_factor();
    let strip = TRIGGER_HEIGHT * scale;

    let right = origin.x as f64 + size.width as f64;
    let bottom = origin.y as f64 + size.height as f64;
    let left = match mascot_window::resting_position(window) {
        Ok(Some(rest)) => rest.x as f64 - TRIGGER_LEFT_SLACK * scale,
        _ => origin.x as f64,
    };

    cursor.x >= left && cursor.x < right && cursor.y >= bottom - strip
}
