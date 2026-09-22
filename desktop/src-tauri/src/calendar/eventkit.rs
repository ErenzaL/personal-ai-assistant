//! The EventKit bridge.
//!
//! `EKEventStore` is neither `Send` nor `Sync`, and Apple asks for one
//! long-lived instance rather than one per call. Both constraints are met the
//! same way: a dedicated worker thread owns the store for the life of the app
//! and is the only thread that ever touches EventKit. Commands post a job to
//! it and wait for the reply, so nothing EventKit-shaped crosses a thread.

use std::sync::mpsc::{self, Receiver, Sender, SyncSender};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use crate::calendar::types::{
    AuthorizationStatus, CalendarError, CalendarErrorCode, CalendarEvent, CalendarInfo, EventChanges, NewEvent,
};

/// How long to wait for the user to answer the system prompt before giving
/// up on the reply. The prompt itself stays on screen; only our wait ends.
const PROMPT_TIMEOUT: Duration = Duration::from_secs(180);

/// A unit of work for the thread that owns the event store.
enum Job {
    Status(SyncSender<AuthorizationStatus>),
    RequestAccess(SyncSender<Result<AuthorizationStatus, CalendarError>>),
    ListCalendars(SyncSender<Result<Vec<CalendarInfo>, CalendarError>>),
    ListEvents {
        start: String,
        end: String,
        calendar_ids: Option<Vec<String>>,
        reply: SyncSender<Result<Vec<CalendarEvent>, CalendarError>>,
    },
    CreateEvent {
        event: NewEvent,
        reply: SyncSender<Result<CalendarEvent, CalendarError>>,
    },
    /// Events starting within the next `horizon_secs`, for the reminder service.
    ListUpcoming {
        horizon_secs: i64,
        reply: SyncSender<Result<Vec<CalendarEvent>, CalendarError>>,
    },
    /// One event by id, read back as EventKit currently has it. Used both to
    /// preserve untouched fields before an update and to resolve "it" across
    /// turns without re-matching by title.
    GetEvent {
        id: String,
        reply: SyncSender<Result<CalendarEvent, CalendarError>>,
    },
    UpdateEvent {
        id: String,
        changes: EventChanges,
        reply: SyncSender<Result<CalendarEvent, CalendarError>>,
    },
    /// Returns the event as it was immediately before removal, so the caller
    /// can say what was actually cancelled without a second round trip.
    DeleteEvent {
        id: String,
        reply: SyncSender<Result<CalendarEvent, CalendarError>>,
    },
}

/// Called (from an EventKit thread) whenever the calendar database changes.
pub type ChangeHook = Box<dyn Fn() + Send + Sync + 'static>;

/// Handle to the EventKit worker. Held in Tauri's managed state.
pub struct CalendarBridge {
    jobs: Mutex<Sender<Job>>,
}

impl CalendarBridge {
    /// Start the worker and create the event store. Called once at startup.
    /// `on_change` runs whenever EventKit reports a change to the database.
    pub fn spawn(on_change: ChangeHook) -> Self {
        let (tx, rx) = mpsc::channel();
        thread::Builder::new()
            .name("eventkit".into())
            .spawn(move || worker(rx, on_change))
            .expect("failed to start the EventKit thread");
        Self {
            jobs: Mutex::new(tx),
        }
    }

    /// A detached handle that can be moved onto a blocking thread.
    ///
    /// The bridge itself lives in Tauri state behind a `Mutex` (a `Sender` is
    /// `Send` but not `Sync`), and its methods block while the worker answers.
    /// Commands must not block the async runtime, so they take a handle and
    /// run it on a blocking thread instead.
    pub fn handle(&self) -> Result<BridgeHandle, CalendarError> {
        let jobs = self
            .jobs
            .lock()
            .map_err(|_| CalendarError::unavailable("The calendar service is in a bad state."))?;
        Ok(BridgeHandle { jobs: jobs.clone() })
    }
}

/// Owned, `Send` handle to the worker. Blocking; use off the async runtime.
#[derive(Clone)]
pub struct BridgeHandle {
    jobs: Sender<Job>,
}

impl BridgeHandle {
    /// Current permission, straight from macOS. Never prompts.
    pub fn authorization_status(&self) -> Result<AuthorizationStatus, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::Status(tx))?;
        rx.recv()
            .map_err(|_| CalendarError::unavailable("The calendar service stopped responding."))
    }

    /// Ask macOS for full access. Shows the system prompt the first time
    /// only; afterwards it returns the existing answer without prompting.
    pub fn request_access(&self) -> Result<AuthorizationStatus, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::RequestAccess(tx))?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// Every event calendar macOS knows about, across all configured accounts.
    pub fn list_calendars(&self) -> Result<Vec<CalendarInfo>, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::ListCalendars(tx))?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// Events overlapping [start, end), oldest first. Dates are ISO 8601;
    /// without an offset they are read as local time.
    pub fn list_events(
        &self,
        start: String,
        end: String,
        calendar_ids: Option<Vec<String>>,
    ) -> Result<Vec<CalendarEvent>, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::ListEvents {
            start,
            end,
            calendar_ids,
            reply: tx,
        })?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// Events starting within the next `horizon_secs`, oldest first.
    pub fn list_upcoming(&self, horizon_secs: i64) -> Result<Vec<CalendarEvent>, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::ListUpcoming { horizon_secs, reply: tx })?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// Write a new event. Only ever called after the user confirms.
    pub fn create_event(&self, event: NewEvent) -> Result<CalendarEvent, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::CreateEvent { event, reply: tx })?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// One event by id, exactly as EventKit currently has it.
    pub fn get_event(&self, id: String) -> Result<CalendarEvent, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::GetEvent { id, reply: tx })?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// Change only the given fields of an existing event. Only ever called
    /// after the user confirms a proposed change.
    pub fn update_event(&self, id: String, changes: EventChanges) -> Result<CalendarEvent, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::UpdateEvent { id, changes, reply: tx })?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    /// Remove an event. Only ever called after the user confirms.
    pub fn delete_event(&self, id: String) -> Result<CalendarEvent, CalendarError> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.post(Job::DeleteEvent { id, reply: tx })?;
        match rx.recv() {
            Ok(result) => result,
            Err(_) => Err(CalendarError::unavailable(
                "The calendar service stopped responding.",
            )),
        }
    }

    fn post(&self, job: Job) -> Result<(), CalendarError> {
        self.jobs
            .send(job)
            .map_err(|_| CalendarError::unavailable("The calendar service is not running."))
    }
}

// --- the worker thread -------------------------------------------------------

#[cfg(target_os = "macos")]
fn worker(rx: Receiver<Job>, on_change: ChangeHook) {
    use objc2_event_kit::EKEventStore;

    // One store for the whole process, owned by this thread and never shared.
    // SAFETY: `new` is the documented initialiser and we are on the thread
    // that will make every subsequent call on it.
    let store = unsafe { EKEventStore::new() };

    // EventKit posts EKEventStoreChangedNotification for this store whenever
    // the calendar database changes (edits in Calendar.app, syncs, permission
    // changes). The token keeps the observer alive as long as this thread.
    let _observer = macos::observe_changes(&store, on_change);

    while let Ok(job) = rx.recv() {
        match job {
            Job::Status(reply) => {
                let _ = reply.send(macos::status());
            }
            Job::RequestAccess(reply) => {
                let _ = reply.send(macos::request_access(&store));
            }
            Job::ListCalendars(reply) => {
                let _ = reply.send(macos::list_calendars(&store));
            }
            Job::ListEvents {
                start,
                end,
                calendar_ids,
                reply,
            } => {
                let _ = reply.send(macos::list_events(&store, &start, &end, calendar_ids.as_deref()));
            }
            Job::CreateEvent { event, reply } => {
                let _ = reply.send(macos::create_event(&store, &event));
            }
            Job::ListUpcoming { horizon_secs, reply } => {
                let _ = reply.send(macos::list_upcoming(&store, horizon_secs));
            }
            Job::GetEvent { id, reply } => {
                let _ = reply.send(macos::get_event(&store, &id));
            }
            Job::UpdateEvent { id, changes, reply } => {
                let _ = reply.send(macos::update_event(&store, &id, &changes));
            }
            Job::DeleteEvent { id, reply } => {
                let _ = reply.send(macos::delete_event(&store, &id));
            }
        }
    }
}

/// Local ISO 8601 (with offset) for a unix time, as the calendar reports it.
#[cfg(target_os = "macos")]
pub fn iso_local(unix: i64) -> String {
    macos::iso_local(unix)
}

#[cfg(not(target_os = "macos"))]
fn worker(rx: Receiver<Job>, _on_change: ChangeHook) {
    while let Ok(job) = rx.recv() {
        match job {
            Job::Status(reply) => {
                let _ = reply.send(AuthorizationStatus::Restricted);
            }
            Job::RequestAccess(reply) => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::ListCalendars(reply) => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::ListEvents { reply, .. } => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::CreateEvent { reply, .. } => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::ListUpcoming { reply, .. } => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::GetEvent { reply, .. } => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::UpdateEvent { reply, .. } => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
            Job::DeleteEvent { reply, .. } => {
                let _ = reply.send(Err(CalendarError::unsupported(
                    "Calendar access is only available on macOS.",
                )));
            }
        }
    }
}

#[cfg(target_os = "macos")]
mod macos {
    use super::*;

    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2::sel;
    use objc2::runtime::NSObjectProtocol;
    use crate::calendar::types::{CalendarEvent, CalendarInfo, EventChanges, NewEvent, SourceType};
    use objc2_core_graphics::CGColor;
    use objc2_event_kit::{
        EKAuthorizationStatus, EKCalendar, EKEntityType, EKEvent, EKEventStore, EKSourceType, EKSpan,
    };
    use objc2::rc::Retained;
    use objc2::runtime::ProtocolObject;
    use objc2_event_kit::EKEventStoreChangedNotification;
    use objc2_foundation::{
        NSArray, NSDate, NSDateFormatter, NSError, NSLocale, NSNotification, NSNotificationCenter,
        NSString, NSTimeZone,
    };
    use std::ptr::NonNull;

    /// Run `on_change` whenever EventKit reports that this store's database
    /// changed. The returned token unregisters the observer when dropped.
    pub(super) fn observe_changes(
        store: &EKEventStore,
        on_change: ChangeHook,
    ) -> Retained<ProtocolObject<dyn NSObjectProtocol>> {
        let block = RcBlock::new(move |_note: NonNull<NSNotification>| on_change());
        // SAFETY: the block captures only a Send + Sync callback; no queue
        // means it runs on the posting thread, which is fine for a wake-up.
        unsafe {
            NSNotificationCenter::defaultCenter().addObserverForName_object_queue_usingBlock(
                Some(EKEventStoreChangedNotification),
                Some(store.as_ref()),
                None,
                &block,
            )
        }
    }

    /// Local ISO 8601 with offset for a unix time.
    pub(super) fn iso_local(unix: i64) -> String {
        let date = NSDate::dateWithTimeIntervalSince1970(unix as f64);
        formatter(ISO_LOCAL).stringFromDate(&date).to_string()
    }

    /// Events starting in the next `horizon_secs`, across every calendar.
    pub(super) fn list_upcoming(
        store: &EKEventStore,
        horizon_secs: i64,
    ) -> Result<Vec<CalendarEvent>, CalendarError> {
        if !status().grants_read() {
            return Err(CalendarError::new(
                CalendarErrorCode::NotAuthorized,
                "Calendar access has not been granted yet.",
            ));
        }
        let from = NSDate::now();
        let to = NSDate::dateWithTimeIntervalSinceNow(horizon_secs.max(60) as f64);
        Ok(events_between(store, &from, &to, None))
    }

    /// Longest note text passed on. Notes can be very long, and only the first
    /// lines are ever useful in a summary.
    const NOTES_MAX: usize = 200;

    /// ISO 8601 with the local offset, e.g. 2026-09-15T14:00:00+09:00.
    const ISO_LOCAL: &str = "yyyy-MM-dd\'T\'HH:mm:ssXXXXX";
    /// Accepted inputs, tried in order. The last two are read as local time.
    const INPUT_FORMATS: [&str; 3] = [
        "yyyy-MM-dd\'T\'HH:mm:ssXXXXX",
        "yyyy-MM-dd\'T\'HH:mm:ss",
        "yyyy-MM-dd",
    ];

    /// A formatter fixed to the local timezone.
    ///
    /// The POSIX locale matters: without it a user with 12-hour time set can
    /// make a fixed `HH` format parse and print incorrectly.
    fn formatter(format: &str) -> objc2::rc::Retained<NSDateFormatter> {
        let f = NSDateFormatter::new();
        f.setLocale(Some(&NSLocale::localeWithLocaleIdentifier(&NSString::from_str(
            "en_US_POSIX",
        ))));
        f.setTimeZone(Some(&NSTimeZone::localTimeZone()));
        f.setDateFormat(Some(&NSString::from_str(format)));
        f
    }

    fn parse_date(text: &str, label: &str) -> Result<objc2::rc::Retained<NSDate>, CalendarError> {
        let value = NSString::from_str(text.trim());
        for format in INPUT_FORMATS {
            if let Some(date) = formatter(format).dateFromString(&value) {
                return Ok(date);
            }
        }
        Err(CalendarError::new(
            CalendarErrorCode::InvalidRange,
            format!("Could not read the {label} date '{text}'."),
        ))
    }

    pub(super) fn status() -> AuthorizationStatus {
        // SAFETY: a class method with no arguments beyond a plain enum; it
        // reads TCC state and cannot prompt.
        let raw = unsafe { EKEventStore::authorizationStatusForEntityType(EKEntityType::Event) };
        translate(raw)
    }

    fn translate(raw: EKAuthorizationStatus) -> AuthorizationStatus {
        match raw {
            EKAuthorizationStatus::Restricted => AuthorizationStatus::Restricted,
            EKAuthorizationStatus::Denied => AuthorizationStatus::Denied,
            EKAuthorizationStatus::FullAccess => AuthorizationStatus::FullAccess,
            EKAuthorizationStatus::WriteOnly => AuthorizationStatus::WriteOnly,
            // Covers NotDetermined and any value a future macOS adds: treat
            // an unknown state as "we have not been granted anything".
            _ => AuthorizationStatus::NotDetermined,
        }
    }

    pub(super) fn request_access(
        store: &EKEventStore,
    ) -> Result<AuthorizationStatus, CalendarError> {
        // `requestFullAccessToEventsWithCompletion:` is macOS 14+. Checking
        // first turns an unsupported OS into a clear error instead of a crash.
        if !store.respondsToSelector(sel!(requestFullAccessToEventsWithCompletion:)) {
            return Err(CalendarError::unsupported(
                "This version of macOS does not support requesting full calendar access.",
            ));
        }

        let (tx, rx) = mpsc::sync_channel::<(bool, Option<String>)>(1);
        let completion = RcBlock::new(move |granted: Bool, error: *mut NSError| {
            let detail = if error.is_null() {
                None
            } else {
                // SAFETY: EventKit hands us a valid NSError for the duration
                // of the callback; we copy the text out immediately.
                Some(unsafe { (*error).localizedDescription() }.to_string())
            };
            // The receiver is gone only if we already timed out; ignore that.
            let _ = tx.send((granted.as_bool(), detail));
        });

        // SAFETY: the block stays alive in `completion` until this function
        // returns, which is after the reply arrives or the wait times out.
        unsafe { store.requestFullAccessToEventsWithCompletion(RcBlock::as_ptr(&completion)) };

        match rx.recv_timeout(PROMPT_TIMEOUT) {
            // Ask macOS again rather than trusting the boolean: it is the
            // authoritative answer and distinguishes denied from restricted.
            Ok((granted, None)) => {
                let after = status();
                // Refused without recording anything: macOS never showed the
                // prompt. Say so plainly instead of leaving the UI unchanged
                // with no explanation.
                if !granted && after == AuthorizationStatus::NotDetermined {
                    return Err(CalendarError::new(
                        CalendarErrorCode::PromptUnavailable,
                        "macOS did not show the permission prompt. This happens when the app is \
                         started from a terminal: grant access from a built app instead \
                         (npm run tauri build), then reopen it.",
                    ));
                }
                Ok(after)
            }
            Ok((granted, Some(detail))) if granted => {
                // Access was given despite a non-fatal error; still fine.
                let _ = detail;
                Ok(status())
            }
            Ok((_, Some(detail))) => Err(CalendarError::new(
                CalendarErrorCode::RequestFailed,
                format!("macOS refused the calendar request: {detail}"),
            )),
            Err(_) => Err(CalendarError::new(
                CalendarErrorCode::Timeout,
                "The calendar permission prompt was not answered.",
            )),
        }
    }

    pub(super) fn list_calendars(store: &EKEventStore) -> Result<Vec<CalendarInfo>, CalendarError> {
        if !status().grants_read() {
            return Err(CalendarError::new(
                CalendarErrorCode::NotAuthorized,
                "Calendar access has not been granted yet.",
            ));
        }

        // SAFETY: reading calendars for an entity type we hold access to.
        let calendars = unsafe { store.calendarsForEntityType(EKEntityType::Event) };
        let default_id = unsafe { store.defaultCalendarForNewEvents() }
            .map(|c| unsafe { c.calendarIdentifier() }.to_string());

        let mut out = Vec::with_capacity(calendars.len());
        for calendar in calendars.iter() {
            let id = unsafe { calendar.calendarIdentifier() }.to_string();
            let is_default = default_id.as_deref() == Some(id.as_str());
            let source = unsafe { calendar.source() };
            out.push(CalendarInfo {
                title: unsafe { calendar.title() }.to_string(),
                // Reported exactly as macOS groups it; never inferred.
                source_name: source
                    .as_ref()
                    .map(|s| unsafe { s.title() }.to_string())
                    .filter(|t| !t.is_empty()),
                source_type: source.as_ref().and_then(|s| translate_source(unsafe { s.sourceType() })),
                allows_modifications: unsafe { calendar.allowsContentModifications() },
                color: hex_color(&calendar),
                is_default,
                id,
            });
        }
        Ok(out)
    }

    fn translate_source(raw: EKSourceType) -> Option<SourceType> {
        match raw {
            EKSourceType::Local => Some(SourceType::Local),
            EKSourceType::Exchange => Some(SourceType::Exchange),
            EKSourceType::CalDAV => Some(SourceType::CalDav),
            EKSourceType::MobileMe => Some(SourceType::MobileMe),
            EKSourceType::Subscribed => Some(SourceType::Subscribed),
            EKSourceType::Birthdays => Some(SourceType::Birthdays),
            // A type this build does not know: say nothing rather than guess.
            _ => None,
        }
    }

    /// `#rrggbb` from the calendar's colour, when the components are in a
    /// space we can read. Returns None rather than approximating.
    fn hex_color(calendar: &EKCalendar) -> Option<String> {
        let color = unsafe { calendar.CGColor() }?;
        let count = CGColor::number_of_components(Some(&color));
        let components = CGColor::components(Some(&color));
        if components.is_null() || count < 2 {
            return None;
        }
        // SAFETY: Core Graphics guarantees `count` readable components.
        let values = unsafe { std::slice::from_raw_parts(components, count) };
        let channel = |v: f64| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
        let (r, g, b) = match count {
            // grayscale + alpha
            2 => (channel(values[0]), channel(values[0]), channel(values[0])),
            // rgb(+alpha)
            3 | 4 => (channel(values[0]), channel(values[1]), channel(values[2])),
            _ => return None,
        };
        Some(format!("#{r:02x}{g:02x}{b:02x}"))
    }

    pub(super) fn list_events(
        store: &EKEventStore,
        start: &str,
        end: &str,
        calendar_ids: Option<&[String]>,
    ) -> Result<Vec<CalendarEvent>, CalendarError> {
        if !status().grants_read() {
            return Err(CalendarError::new(
                CalendarErrorCode::NotAuthorized,
                "Calendar access has not been granted yet.",
            ));
        }

        let from = parse_date(start, "start")?;
        let to = parse_date(end, "end")?;
        if to.timeIntervalSince1970() <= from.timeIntervalSince1970() {
            return Err(CalendarError::new(
                CalendarErrorCode::InvalidRange,
                "The end of the range must be after the start.",
            ));
        }

        // None searches every calendar; a list narrows it. Unknown ids are
        // ignored rather than treated as an error.
        let wanted: Option<objc2::rc::Retained<NSArray<EKCalendar>>> = match calendar_ids {
            Some(ids) if !ids.is_empty() => {
                let all = unsafe { store.calendarsForEntityType(EKEntityType::Event) };
                let picked: Vec<_> = all
                    .iter()
                    .filter(|c| ids.iter().any(|id| *id == unsafe { c.calendarIdentifier() }.to_string()))
                    .collect();
                if picked.is_empty() {
                    return Ok(Vec::new());
                }
                Some(NSArray::from_retained_slice(&picked))
            }
            _ => None,
        };

        Ok(events_between(store, &from, &to, wanted.as_deref()))
    }

    /// Every occurrence overlapping [from, to), oldest first.
    fn events_between(
        store: &EKEventStore,
        from: &NSDate,
        to: &NSDate,
        wanted: Option<&NSArray<EKCalendar>>,
    ) -> Vec<CalendarEvent> {
        // SAFETY: the predicate comes from this same store, which is what
        // `eventsMatchingPredicate` requires.
        let predicate = unsafe {
            store.predicateForEventsWithStartDate_endDate_calendars(from, to, wanted)
        };
        let events = unsafe { store.eventsMatchingPredicate(&predicate) };

        let iso = formatter(ISO_LOCAL);
        // EventKit gives no guaranteed order, so sort by actual start time.
        let mut rows: Vec<(f64, CalendarEvent)> = Vec::with_capacity(events.len());
        for event in events.iter() {
            if let Some(row) = describe(&event, &iso) {
                rows.push(row);
            }
        }
        rows.sort_by(|a, b| a.0.total_cmp(&b.0));
        rows.into_iter().map(|(_, event)| event).collect()
    }

    /// Convert one occurrence, or skip it if it has no calendar (EventKit can
    /// return detached occurrences during a sync).
    fn describe(
        event: &EKEvent,
        iso: &NSDateFormatter,
    ) -> Option<(f64, CalendarEvent)> {
        let calendar = unsafe { event.calendar() }?;
        let start = unsafe { event.startDate() };
        let end = unsafe { event.endDate() };
        let sort_key = start.timeIntervalSince1970();

        let text = |value: Option<objc2::rc::Retained<NSString>>, limit: Option<usize>| {
            value.map(|v| v.to_string()).and_then(|v| {
                let trimmed = v.trim().to_string();
                if trimmed.is_empty() {
                    return None;
                }
                Some(match limit {
                    Some(max) if trimmed.chars().count() > max => {
                        trimmed.chars().take(max).collect::<String>() + "…"
                    }
                    _ => trimmed,
                })
            })
        };

        Some((
            sort_key,
            CalendarEvent {
                id: unsafe { event.eventIdentifier() }.map(|v| v.to_string()),
                title: unsafe { event.title() }.to_string(),
                start: iso.stringFromDate(&start).to_string(),
                end: iso.stringFromDate(&end).to_string(),
                start_unix: start.timeIntervalSince1970() as i64,
                end_unix: end.timeIntervalSince1970() as i64,
                all_day: unsafe { event.isAllDay() },
                calendar_id: unsafe { calendar.calendarIdentifier() }.to_string(),
                calendar_title: unsafe { calendar.title() }.to_string(),
                location: text(unsafe { event.location() }, None),
                notes: text(unsafe { event.notes() }, Some(NOTES_MAX)),
            },
        ))
    }

    pub(super) fn create_event(
        store: &EKEventStore,
        new: &NewEvent,
    ) -> Result<CalendarEvent, CalendarError> {
        if !status().grants_read() {
            return Err(CalendarError::new(
                CalendarErrorCode::NotAuthorized,
                "Calendar access has not been granted yet.",
            ));
        }
        let title = new.title.trim();
        if title.is_empty() {
            return Err(CalendarError::new(
                CalendarErrorCode::InvalidRange,
                "The event needs a title.",
            ));
        }

        let start = parse_date(&new.start, "start")?;
        let end = parse_date(&new.end, "end")?;
        if end.timeIntervalSince1970() <= start.timeIntervalSince1970() {
            return Err(CalendarError::new(
                CalendarErrorCode::InvalidRange,
                "The event must end after it starts.",
            ));
        }

        // Named calendar if given, otherwise whatever macOS uses for new events.
        let calendar = match new.calendar_id.as_deref() {
            Some(id) if !id.is_empty() => unsafe { store.calendarsForEntityType(EKEntityType::Event) }
                .iter()
                .find(|c| unsafe { c.calendarIdentifier() }.to_string() == id)
                .ok_or_else(|| {
                    CalendarError::new(
                        CalendarErrorCode::NotFound,
                        "That calendar no longer exists.",
                    )
                })?,
            _ => unsafe { store.defaultCalendarForNewEvents() }.ok_or_else(|| {
                CalendarError::new(
                    CalendarErrorCode::NotFound,
                    "macOS has no default calendar for new events.",
                )
            })?,
        };
        if !unsafe { calendar.allowsContentModifications() } {
            return Err(CalendarError::new(
                CalendarErrorCode::ReadOnlyCalendar,
                format!(
                    "'{}' does not accept new events. Pick a different calendar.",
                    unsafe { calendar.title() }
                ),
            ));
        }

        // SAFETY: the event is built from, and saved to, this same store,
        // which is what EventKit requires.
        let event = unsafe { EKEvent::eventWithEventStore(store) };
        unsafe {
            event.setTitle(Some(&NSString::from_str(title)));
            event.setStartDate(Some(&start));
            event.setEndDate(Some(&end));
            event.setCalendar(Some(&calendar));
            if let Some(text) = new.location.as_deref().map(str::trim).filter(|t| !t.is_empty()) {
                event.setLocation(Some(&NSString::from_str(text)));
            }
            if let Some(text) = new.notes.as_deref().map(str::trim).filter(|t| !t.is_empty()) {
                event.setNotes(Some(&NSString::from_str(text)));
            }
        }

        unsafe { store.saveEvent_span_error(&event, EKSpan::ThisEvent) }.map_err(|err| {
            CalendarError::new(
                CalendarErrorCode::SaveFailed,
                format!("macOS would not save the event: {}", err.localizedDescription()),
            )
        })?;

        // Report back what was actually stored, not what we asked for.
        describe(&event, &formatter(ISO_LOCAL))
            .map(|(_, stored)| stored)
            .ok_or_else(|| {
                CalendarError::new(CalendarErrorCode::SaveFailed, "The event was saved but could not be read back.")
            })
    }

    /// Fetch one existing event by id, as EventKit currently has it. Never
    /// mutates anything.
    fn fetch_event(
        store: &EKEventStore,
        id: &str,
    ) -> Result<objc2::rc::Retained<EKEvent>, CalendarError> {
        if !status().grants_read() {
            return Err(CalendarError::new(
                CalendarErrorCode::NotAuthorized,
                "Calendar access has not been granted yet.",
            ));
        }
        // SAFETY: reading an event by an id this app already holds (from an
        // earlier list/create), for an entity type we hold access to.
        unsafe { store.eventWithIdentifier(&NSString::from_str(id)) }.ok_or_else(|| {
            CalendarError::new(
                CalendarErrorCode::NotFound,
                "That event no longer exists -- it may have already been changed or removed.",
            )
        })
    }

    pub(super) fn get_event(store: &EKEventStore, id: &str) -> Result<CalendarEvent, CalendarError> {
        let event = fetch_event(store, id)?;
        describe(&event, &formatter(ISO_LOCAL)).map(|(_, found)| found).ok_or_else(|| {
            CalendarError::new(CalendarErrorCode::NotFound, "That event could not be read.")
        })
    }

    pub(super) fn update_event(
        store: &EKEventStore,
        id: &str,
        changes: &EventChanges,
    ) -> Result<CalendarEvent, CalendarError> {
        let event = fetch_event(store, id)?;

        let current_calendar = unsafe { event.calendar() }.ok_or_else(|| {
            CalendarError::new(CalendarErrorCode::NotFound, "That event has no calendar and cannot be changed.")
        })?;
        if !unsafe { current_calendar.allowsContentModifications() } {
            return Err(CalendarError::new(
                CalendarErrorCode::ReadOnlyCalendar,
                format!("'{}' does not allow changes to its events.", unsafe { current_calendar.title() }),
            ));
        }

        if let Some(title) = changes.title.as_deref().map(str::trim) {
            if title.is_empty() {
                return Err(CalendarError::new(CalendarErrorCode::InvalidInput, "The title cannot be empty."));
            }
            unsafe { event.setTitle(Some(&NSString::from_str(title))) };
        }

        // Start/end are applied independently, then checked together against
        // whichever side (new or already-on-the-event) ends up in effect --
        // the caller (the frontend) is expected to send both when changing
        // either, computed from the event's own current duration, but this
        // stays correct even if only one side is ever sent.
        if let Some(start) = changes.start.as_deref() {
            let parsed = parse_date(start, "start")?;
            unsafe { event.setStartDate(Some(&parsed)) };
        }
        if let Some(end) = changes.end.as_deref() {
            let parsed = parse_date(end, "end")?;
            unsafe { event.setEndDate(Some(&parsed)) };
        }
        let effective_start = unsafe { event.startDate() };
        let effective_end = unsafe { event.endDate() };
        if effective_end.timeIntervalSince1970() <= effective_start.timeIntervalSince1970() {
            return Err(CalendarError::new(
                CalendarErrorCode::InvalidRange,
                "The event must end after it starts.",
            ));
        }

        if let Some(calendar_id) = changes.calendar_id.as_deref().filter(|c| !c.is_empty()) {
            let target = unsafe { store.calendarsForEntityType(EKEntityType::Event) }
                .iter()
                .find(|c| unsafe { c.calendarIdentifier() }.to_string() == calendar_id)
                .ok_or_else(|| {
                    CalendarError::new(CalendarErrorCode::NotFound, "That calendar no longer exists.")
                })?;
            if !unsafe { target.allowsContentModifications() } {
                return Err(CalendarError::new(
                    CalendarErrorCode::ReadOnlyCalendar,
                    format!("'{}' does not accept events. Pick a different calendar.", unsafe { target.title() }),
                ));
            }
            unsafe { event.setCalendar(Some(&target)) };
        }

        if let Some(location) = changes.location.as_deref() {
            let trimmed = location.trim();
            let value = (!trimmed.is_empty()).then(|| NSString::from_str(trimmed));
            unsafe { event.setLocation(value.as_deref()) };
        }
        if let Some(notes) = changes.notes.as_deref() {
            let trimmed = notes.trim();
            let value = (!trimmed.is_empty()).then(|| NSString::from_str(trimmed));
            unsafe { event.setNotes(value.as_deref()) };
        }

        unsafe { store.saveEvent_span_error(&event, EKSpan::ThisEvent) }.map_err(|err| {
            CalendarError::new(
                CalendarErrorCode::SaveFailed,
                format!("macOS would not save the change: {}", err.localizedDescription()),
            )
        })?;

        describe(&event, &formatter(ISO_LOCAL))
            .map(|(_, stored)| stored)
            .ok_or_else(|| {
                CalendarError::new(CalendarErrorCode::SaveFailed, "The change was saved but could not be read back.")
            })
    }

    pub(super) fn delete_event(store: &EKEventStore, id: &str) -> Result<CalendarEvent, CalendarError> {
        let event = fetch_event(store, id)?;

        let calendar = unsafe { event.calendar() };
        if let Some(calendar) = &calendar {
            if !unsafe { calendar.allowsContentModifications() } {
                return Err(CalendarError::new(
                    CalendarErrorCode::ReadOnlyCalendar,
                    format!("'{}' does not allow removing its events.", unsafe { calendar.title() }),
                ));
            }
        }

        // Captured before removal -- this is what the caller shows as "what
        // was cancelled", since there is nothing left to read back after.
        let snapshot = describe(&event, &formatter(ISO_LOCAL)).map(|(_, found)| found).ok_or_else(|| {
            CalendarError::new(CalendarErrorCode::NotFound, "That event could not be read.")
        })?;

        unsafe { store.removeEvent_span_error(&event, EKSpan::ThisEvent) }.map_err(|err| {
            CalendarError::new(
                CalendarErrorCode::SaveFailed,
                format!("macOS would not remove the event: {}", err.localizedDescription()),
            )
        })?;

        Ok(snapshot)
    }
}
