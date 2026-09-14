//! Commands the React frontend can invoke.

use std::sync::atomic::Ordering;

use tauri::{AppHandle, Manager, WebviewWindow};

use crate::activation::VisibilityFlags;
use crate::mascot_window::{self, Mode};

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

    let mode = if open { Mode::Chat } else { Mode::Mascot };
    mascot_window::set_mode(&window, mode).map_err(|e| e.to_string())?;

    window.set_focusable(open).map_err(|e| e.to_string())?;
    if open {
        window.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}
