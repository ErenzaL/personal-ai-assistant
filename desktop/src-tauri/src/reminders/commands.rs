//! What the React popup can ask for. Every command acts on the one stored
//! record, so the popup and the native notification can never diverge.

use tauri::{AppHandle, State};

use crate::reminders::{ReminderView, Reminders};

const MAX_KEY_CHARS: usize = 256;
const MAX_SNOOZE_MINUTES: i64 = 24 * 60;

fn valid_key(key: &str) -> Result<(), String> {
    if key.is_empty() || key.chars().count() > MAX_KEY_CHARS {
        return Err("That reminder is not valid.".into());
    }
    Ok(())
}

/// The reminder whose popup should be showing right now, if any. Called when
/// the UI loads, so a popup survives a restart of the app.
#[tauri::command]
pub fn reminder_active(reminders: State<'_, Reminders>) -> Option<ReminderView> {
    reminders.active()
}

#[tauri::command]
pub fn reminder_snooze(
    app: AppHandle,
    reminders: State<'_, Reminders>,
    key: String,
    minutes: i64,
) -> Result<Option<ReminderView>, String> {
    valid_key(&key)?;
    if !(1..=MAX_SNOOZE_MINUTES).contains(&minutes) {
        return Err(format!("Snooze must be between 1 and {MAX_SNOOZE_MINUTES} minutes."));
    }
    let view = reminders.snooze(&key, minutes);
    crate::commands::apply_reminder_open(&app, false)?;
    Ok(view)
}

#[tauri::command]
pub fn reminder_dismiss(
    app: AppHandle,
    reminders: State<'_, Reminders>,
    key: String,
) -> Result<Option<ReminderView>, String> {
    valid_key(&key)?;
    let view = reminders.dismiss(&key);
    crate::commands::apply_reminder_open(&app, false)?;
    Ok(view)
}
