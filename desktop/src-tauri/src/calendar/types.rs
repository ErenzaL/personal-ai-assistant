//! Types crossing the boundary to the frontend. Mirrored in
//! `src/types/calendar.ts`.

use serde::{Deserialize, Serialize};

/// Calendar permission as macOS reports it.
///
/// `WriteOnly` is included because macOS can return it (an app may hold
/// write-only access), even though this app always asks for full access.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthorizationStatus {
    /// Never asked. The next request shows the system prompt.
    NotDetermined,
    /// Blocked by policy (parental controls, MDM). Asking will not help.
    Restricted,
    /// The user said no. Only System Settings can change this.
    Denied,
    /// Read and write.
    FullAccess,
    /// Can add events but not read them.
    WriteOnly,
}

impl AuthorizationStatus {
    /// True once the app may read events. Write-only is deliberately not
    /// "granted" here: this app needs to read as well.
    pub fn grants_read(self) -> bool {
        matches!(self, Self::FullAccess)
    }
}

/// What both commands return.
#[derive(Debug, Clone, Serialize)]
pub struct CalendarAuthorization {
    pub status: AuthorizationStatus,
    /// Convenience for the UI, so it does not re-derive the rule.
    pub can_read: bool,
    /// True when asking again could still show a prompt. False once the user
    /// has answered, or when policy forbids it.
    pub can_request: bool,
}

impl From<AuthorizationStatus> for CalendarAuthorization {
    fn from(status: AuthorizationStatus) -> Self {
        Self {
            status,
            can_read: status.grants_read(),
            can_request: status == AuthorizationStatus::NotDetermined,
        }
    }
}

/// One calendar available through EventKit.
///
/// Everything here is read straight from EventKit. In particular the provider
/// is *not* inferred: `source_name` is whatever macOS itself groups the
/// calendar under ("iCloud", "Google", "Other"), and `source_type` is
/// EventKit's own classification. A CalDAV calendar is reported as CalDAV,
/// never guessed to be one service or another.
#[derive(Debug, Clone, Serialize)]
pub struct CalendarInfo {
    /// EventKit's stable identifier. Preserved verbatim; use it to refer back
    /// to this calendar later.
    pub id: String,
    pub title: String,
    /// The account/group macOS files this calendar under, if EventKit has one.
    pub source_name: Option<String>,
    /// EventKit's source classification, or `None` if it reports something
    /// this build does not recognise.
    pub source_type: Option<SourceType>,
    /// False for subscribed or otherwise read-only calendars; events cannot
    /// be added to those.
    pub allows_modifications: bool,
    /// `#rrggbb`, when EventKit exposes a colour in a convertible space.
    pub color: Option<String>,
    /// True for the calendar macOS itself uses for new events.
    pub is_default: bool,
}

/// EventKit's own source types. Reported as-is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceType {
    Local,
    Exchange,
    CalDav,
    MobileMe,
    Subscribed,
    Birthdays,
}

/// One occurrence of an event, already resolved to the user's local time.
///
/// Recurring events are expanded by EventKit, so each occurrence appears
/// separately. `start`/`end` are ISO 8601 with the local UTC offset; for
/// all-day events they are local midnight boundaries and only the date part
/// is meaningful.
#[derive(Debug, Clone, Serialize)]
pub struct CalendarEvent {
    /// EventKit's identifier. Shared by every occurrence of a recurring event.
    pub id: Option<String>,
    pub title: String,
    pub start: String,
    pub end: String,
    /// The same instants as unix seconds, for arithmetic without date parsing.
    pub start_unix: i64,
    pub end_unix: i64,
    pub all_day: bool,
    pub calendar_id: String,
    pub calendar_title: String,
    pub location: Option<String>,
    /// Truncated; only present when the event actually has notes.
    pub notes: Option<String>,
}

/// What the caller wants created. Times are local ISO 8601; the calendar
/// falls back to the user's default when `calendar_id` is omitted.
#[derive(Debug, Clone, Deserialize)]
pub struct NewEvent {
    pub title: String,
    pub start: String,
    pub end: String,
    pub calendar_id: Option<String>,
    pub location: Option<String>,
    pub notes: Option<String>,
}

/// Structured failure. Shape matches the errors the FastAPI layer returns
/// (`code` + `message`), so the frontend handles both the same way.
#[derive(Debug, Clone, Serialize)]
pub struct CalendarError {
    pub code: CalendarErrorCode,
    pub message: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CalendarErrorCode {
    /// Not macOS, or EventKit is missing the API this build needs.
    Unsupported,
    /// The EventKit worker thread is not running.
    Unavailable,
    /// EventKit reported an error while asking for access.
    RequestFailed,
    /// The prompt was never answered within the timeout.
    Timeout,
    /// Calendar access has not been granted, so there is nothing to read.
    NotAuthorized,
    /// A start/end date could not be understood, or the range is backwards.
    InvalidRange,
    /// A command argument is missing, too long, or otherwise unusable.
    InvalidInput,
    /// The chosen calendar (or the macOS default) could not be found.
    NotFound,
    /// The chosen calendar does not accept new events (subscribed, holidays).
    ReadOnlyCalendar,
    /// EventKit refused to save.
    SaveFailed,
    /// macOS refused to even show the prompt. This is what happens under
    /// `tauri dev`: a binary launched from a terminal is attributed to the
    /// terminal, not to the app, so EventKit declines immediately.
    PromptUnavailable,
}

impl CalendarError {
    pub fn new(code: CalendarErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    pub fn unsupported(message: impl Into<String>) -> Self {
        Self::new(CalendarErrorCode::Unsupported, message)
    }

    pub fn unavailable(message: impl Into<String>) -> Self {
        Self::new(CalendarErrorCode::Unavailable, message)
    }
}
