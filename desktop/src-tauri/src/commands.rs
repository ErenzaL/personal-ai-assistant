//! Commands the React frontend can invoke.

use std::sync::atomic::Ordering;

use tauri::{AppHandle, Manager, WebviewWindow};

use crate::activation::VisibilityFlags;
use crate::mascot_window::{self, Mode};
use crate::platform::{self, LoginItem};
use crate::reminders::Reminders;

/// Open or close the chat panel at the native level.
///
/// Does three things that must stay in sync:
/// 1. Flags `chat_open` so the activation poller stops auto-hiding.
/// 2. Resizes the window (keeping the mascot anchored bottom-right).
/// 3. Makes the window focusable while chat is open so the text input can
///    receive keystrokes, and non-focusable again afterwards so the mascot
///    never steals focus from other apps.
#[tauri::command]
pub fn set_chat_open(app: AppHandle, window: WebviewWindow, open: bool) -> Result<(), String> {
    app.state::<VisibilityFlags>()
        .chat_open
        .store(open, Ordering::Relaxed);

    // Closing the chat while a reminder popup is up keeps room for the popup.
    let reminder_open = app.state::<VisibilityFlags>().reminder_open.load(Ordering::Relaxed);
    let mode = match (open, reminder_open) {
        (true, _) => Mode::Chat,
        (false, true) => Mode::Reminder,
        (false, false) => Mode::Mascot,
    };
    mascot_window::set_mode(&window, mode).map_err(|e| e.to_string())?;

    window.set_focusable(open).map_err(|e| e.to_string())?;
    if open {
        window.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Show or hide room for the reminder popup and pin the window while it is up.
///
/// Used by the reminder service when an alert fires and by the snooze and
/// dismiss commands afterwards. With the chat open the popup renders inside
/// the chat area, so only the pin changes.
pub fn apply_reminder_open(app: &AppHandle, open: bool) -> Result<(), String> {
    let flags = app.state::<VisibilityFlags>();
    flags.reminder_open.store(open, Ordering::Relaxed);
    if flags.chat_open.load(Ordering::Relaxed) {
        return Ok(());
    }
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is missing".to_string())?;
    let mode = if open { Mode::Reminder } else { Mode::Mascot };
    mascot_window::set_mode(&window, mode).map_err(|e| e.to_string())
}

/// The stored settings the native side enforces. The UI pushes them when
/// they load and whenever they change; the backend's SQLite is the record.
#[tauri::command]
pub fn apply_settings(
    app: AppHandle,
    edge_activation: bool,
    reminder_minutes: i64,
    calendar_notifications: bool,
) {
    app.state::<VisibilityFlags>()
        .edge_enabled
        .store(edge_activation, Ordering::Relaxed);
    app.state::<Reminders>()
        .configure(reminder_minutes, calendar_notifications);
}

/// Whether macOS starts this app at login. Read live from the system, never
/// stored: the user can change it in System Settings as well.
#[tauri::command]
pub fn login_item_status() -> LoginItem {
    platform::login_item_status()
}

#[tauri::command]
pub fn set_login_item(enabled: bool) -> Result<LoginItem, String> {
    platform::set_login_item(enabled)
}
