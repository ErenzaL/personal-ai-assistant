//! Tauri commands for calendar permission. Nothing here touches FastAPI.
//!
//! Both commands block while the EventKit worker answers -- the access
//! request can sit there for as long as the user leaves the system prompt on
//! screen -- so the work runs on a blocking thread rather than on the async
//! runtime.

use tauri::State;

use crate::calendar::eventkit::{BridgeHandle, CalendarBridge};
use crate::calendar::types::{
    CalendarAuthorization, CalendarError, CalendarErrorCode, CalendarEvent, CalendarInfo, NewEvent,
};

/// Upper bounds on command arguments. Nothing legitimate comes near them;
/// they stop a malformed or hostile call from reaching EventKit.
const MAX_DATE_CHARS: usize = 64;
const MAX_ID_CHARS: usize = 256;
const MAX_IDS: usize = 64;
const MAX_TITLE_CHARS: usize = 500;
const MAX_LOCATION_CHARS: usize = 500;
const MAX_NOTES_CHARS: usize = 5000;

fn bounded(value: &str, max: usize, what: &str) -> Result<(), CalendarError> {
    if value.chars().count() > max {
        return Err(CalendarError::new(
            CalendarErrorCode::InvalidInput,
            format!("The {what} is too long."),
        ));
    }
    Ok(())
}

async fn off_runtime<F>(bridge: State<'_, CalendarBridge>, work: F) -> Result<CalendarAuthorization, CalendarError>
where
    F: FnOnce(BridgeHandle) -> Result<crate::calendar::types::AuthorizationStatus, CalendarError>
        + Send
        + 'static,
{
    let handle = bridge.handle()?;
    tauri::async_runtime::spawn_blocking(move || work(handle))
        .await
        .map_err(|_| CalendarError::unavailable("The calendar request was interrupted."))?
        .map(Into::into)
}

/// Current calendar permission. Never shows a prompt, so it is safe to call
/// on every render.
#[tauri::command]
pub async fn calendar_get_authorization_status(
    bridge: State<'_, CalendarBridge>,
) -> Result<CalendarAuthorization, CalendarError> {
    off_runtime(bridge, |handle| handle.authorization_status()).await
}

/// Ask macOS for full calendar access (read now, create later).
///
/// The system prompt appears only the first time. After that this returns the
/// standing answer immediately, and only System Settings can change it.
#[tauri::command]
pub async fn calendar_request_access(
    bridge: State<'_, CalendarBridge>,
) -> Result<CalendarAuthorization, CalendarError> {
    off_runtime(bridge, |handle| handle.request_access()).await
}

/// Every event calendar macOS knows about, from all configured accounts
/// (iCloud, Google, Exchange, subscribed feeds). Requires access.
#[tauri::command]
pub async fn calendar_list_calendars(
    bridge: State<'_, CalendarBridge>,
) -> Result<Vec<CalendarInfo>, CalendarError> {
    let handle = bridge.handle()?;
    tauri::async_runtime::spawn_blocking(move || handle.list_calendars())
        .await
        .map_err(|_| CalendarError::unavailable("The calendar request was interrupted."))?
}

/// Events overlapping [start_datetime, end_datetime), oldest first.
///
/// Dates are ISO 8601; without an offset they are read as the user's local
/// time. `calendar_ids` narrows the search; omit it to search every calendar.
/// Recurring events come back as individual occurrences.
#[tauri::command]
pub async fn calendar_list_events(
    bridge: State<'_, CalendarBridge>,
    start_datetime: String,
    end_datetime: String,
    calendar_ids: Option<Vec<String>>,
) -> Result<Vec<CalendarEvent>, CalendarError> {
    bounded(&start_datetime, MAX_DATE_CHARS, "start date")?;
    bounded(&end_datetime, MAX_DATE_CHARS, "end date")?;
    if let Some(ids) = &calendar_ids {
        if ids.len() > MAX_IDS {
            return Err(CalendarError::new(CalendarErrorCode::InvalidInput, "Too many calendars."));
        }
        for id in ids {
            bounded(id, MAX_ID_CHARS, "calendar id")?;
        }
    }
    let handle = bridge.handle()?;
    tauri::async_runtime::spawn_blocking(move || {
        handle.list_events(start_datetime, end_datetime, calendar_ids)
    })
    .await
    .map_err(|_| CalendarError::unavailable("The calendar request was interrupted."))?
}

/// Write one event to the calendar.
///
/// Called only after the user confirms a proposal in the chat panel: nothing
/// in the assistant path reaches this without an explicit press of Confirm.
#[tauri::command]
pub async fn calendar_create_event(
    bridge: State<'_, CalendarBridge>,
    event: NewEvent,
) -> Result<CalendarEvent, CalendarError> {
    if event.title.trim().is_empty() {
        return Err(CalendarError::new(CalendarErrorCode::InvalidInput, "The event needs a title."));
    }
    bounded(&event.title, MAX_TITLE_CHARS, "title")?;
    bounded(&event.start, MAX_DATE_CHARS, "start date")?;
    bounded(&event.end, MAX_DATE_CHARS, "end date")?;
    bounded(event.calendar_id.as_deref().unwrap_or(""), MAX_ID_CHARS, "calendar id")?;
    bounded(event.location.as_deref().unwrap_or(""), MAX_LOCATION_CHARS, "location")?;
    bounded(event.notes.as_deref().unwrap_or(""), MAX_NOTES_CHARS, "notes")?;
    let handle = bridge.handle()?;
    tauri::async_runtime::spawn_blocking(move || handle.create_event(event))
        .await
        .map_err(|_| CalendarError::unavailable("The calendar request was interrupted."))?
}

/// Open System Settings at Privacy & Security > Calendars. A fixed URL with
/// no arguments, so nothing from the webview can change where it goes.
#[tauri::command]
pub fn calendar_open_settings() -> Result<(), CalendarError> {
    std::process::Command::new("open")
        .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars")
        .spawn()
        .map(|_| ())
        .map_err(|_| CalendarError::unavailable("Could not open System Settings."))
}
