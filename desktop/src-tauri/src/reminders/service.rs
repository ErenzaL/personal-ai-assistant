//! The scheduling thread and what the rest of the app can ask of it.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, SyncSender};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_notification::NotificationExt;

use crate::activation::VisibilityFlags;
use crate::calendar::eventkit::BridgeHandle;
use crate::calendar::types::CalendarEvent;
use crate::reminders::store::{Reminder, Store, DEFAULT_LEAD_SECS, DEMO_EVENT_ID};

/// How far ahead to look. Anything later is picked up on a later pass.
const HORIZON_SECS: i64 = 24 * 60 * 60;
/// Longest pause between passes when nothing is due sooner. EventKit change
/// notifications wake the thread earlier when the calendar changes.
const REFRESH_SECS: i64 = 60;
/// Event name the React side listens for.
pub const FIRED_EVENT: &str = "reminder:fired";

/// What the popup and the notification are built from.
#[derive(Debug, Clone, Serialize)]
pub struct ReminderView {
    pub key: String,
    pub title: String,
    pub start: String,
    pub start_unix: i64,
    pub minutes_until: i64,
    pub snoozed_until: Option<i64>,
}

impl ReminderView {
    fn of(reminder: &Reminder, now: i64) -> Self {
        Self {
            key: reminder.key.clone(),
            title: reminder.title.clone(),
            start: reminder.start.clone(),
            start_unix: reminder.start_unix,
            minutes_until: minutes_between(now, reminder.start_unix),
            snoozed_until: reminder.snoozed_until,
        }
    }
}

/// The two settings the thread honours, pushed from the stored settings by
/// the UI. Defaults apply until the first push (10 minutes, alerts on).
pub struct ReminderSettings {
    lead_secs: AtomicI64,
    notify: AtomicBool,
}

impl Default for ReminderSettings {
    fn default() -> Self {
        Self {
            lead_secs: AtomicI64::new(DEFAULT_LEAD_SECS),
            notify: AtomicBool::new(true),
        }
    }
}

/// Tauri-managed handle to the service.
pub struct Reminders {
    app: AppHandle,
    store: Arc<Mutex<Store>>,
    settings: Arc<ReminderSettings>,
    wake: SyncSender<()>,
}

impl Reminders {
    /// Load the file and start the thread. `wake_rx` is the other end of the
    /// channel the EventKit bridge signals when the calendar changes.
    pub fn start(
        app: AppHandle,
        calendar: BridgeHandle,
        wake_tx: SyncSender<()>,
        wake_rx: Receiver<()>,
    ) -> Self {
        let path = app
            .path()
            .app_data_dir()
            .map(|dir| dir.join("reminders.json"))
            .unwrap_or_else(|_| PathBuf::from("reminders.json"));
        let store = Arc::new(Mutex::new(Store::load(path)));
        let settings = Arc::new(ReminderSettings::default());

        let shared = Arc::clone(&store);
        let shared_settings = Arc::clone(&settings);
        let handle = app.clone();
        thread::Builder::new()
            .name("reminders".into())
            .spawn(move || run(handle, calendar, shared, shared_settings, wake_rx))
            .expect("failed to start the reminder thread");

        Self {
            app,
            store,
            settings,
            wake: wake_tx,
        }
    }

    /// Apply the stored settings: how many minutes before an event to alert,
    /// and whether to alert at all. Pending reminders move with the lead.
    pub fn configure(&self, minutes: i64, notifications: bool) {
        let minutes = minutes.clamp(1, 120);
        self.settings.lead_secs.store(minutes * 60, Ordering::Relaxed);
        self.settings.notify.store(notifications, Ordering::Relaxed);
        let _ = self.wake.try_send(());
    }

    /// The reminder that has alerted and is waiting on the user, if any.
    pub fn active(&self) -> Option<ReminderView> {
        let now = unix_now();
        self.lock().items.iter().find(|r| r.awaiting_user(now)).map(|r| ReminderView::of(r, now))
    }

    /// Push the same reminder back by `minutes`; it alerts again then.
    pub fn snooze(&self, key: &str, minutes: i64) -> Option<ReminderView> {
        let now = unix_now();
        let view = {
            let mut store = self.lock();
            let reminder = store.get_mut(key)?;
            reminder.snooze(minutes, now);
            let view = ReminderView::of(reminder, now);
            log_save(store.save());
            view
        };
        eprintln!("reminders: snoozed {key} for {minutes} min");
        let _ = self.wake.try_send(());
        Some(view)
    }

    /// Stop this reminder for good.
    pub fn dismiss(&self, key: &str) -> Option<ReminderView> {
        let now = unix_now();
        let view = {
            let mut store = self.lock();
            let reminder = store.get_mut(key)?;
            reminder.dismiss();
            let view = ReminderView::of(reminder, now);
            log_save(store.save());
            view
        };
        eprintln!("reminders: dismissed {key}");
        Some(view)
    }

    /// `--demo-reminder`: a fake event starting soon whose alert is already
    /// due, so the whole path (notification, reveal, popup, snooze) can be
    /// tried without waiting for a real event.
    pub fn add_demo(&self, in_minutes: i64) {
        let now = unix_now();
        let start = now + in_minutes * 60;
        let lead = self.settings.lead_secs.load(Ordering::Relaxed);
        let mut reminder = Reminder::for_event(DEMO_EVENT_ID, "Project Meeting", &iso_local(start), start, lead);
        reminder.remind_at = now;
        let mut store = self.lock();
        store.items.retain(|r| r.event_id != DEMO_EVENT_ID);
        store.items.push(reminder);
        log_save(store.save());
        drop(store);
        let _ = self.wake.try_send(());
    }

    fn lock(&self) -> MutexGuard<'_, Store> {
        self.store.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// Bring the popup for an already-alerted reminder back after a restart.
    /// No notification is sent again: that alert went out before.
    pub fn restore_popup(&self) {
        if let Some(view) = self.active() {
            reveal(&self.app, &view);
        }
    }
}

fn run(
    app: AppHandle,
    calendar: BridgeHandle,
    store: Arc<Mutex<Store>>,
    settings: Arc<ReminderSettings>,
    wake: Receiver<()>,
) {
    let mut calendar_ok: Option<bool> = None;
    loop {
        let now = unix_now();
        let lead = settings.lead_secs.load(Ordering::Relaxed);
        let lookup = calendar.list_upcoming(HORIZON_SECS);
        let ok = lookup.is_ok();
        if calendar_ok != Some(ok) {
            match &lookup {
                Ok(events) => eprintln!("reminders: calendar reachable, {} upcoming event(s)", events.len()),
                Err(err) => eprintln!("reminders: calendar unavailable ({}); will keep trying", err.message),
            }
            calendar_ok = Some(ok);
        }

        let due = {
            let mut guard = store.lock().unwrap_or_else(|p| p.into_inner());
            let mut changed = match lookup {
                Ok(events) => reconcile(&mut guard, &events, now, lead),
                Err(_) => false,
            };
            let due = take_due(&mut guard, now);
            changed |= !due.is_empty();
            if changed {
                log_save(guard.save());
            }
            due
        };
        // Alerts go out only after `sent` is on disk, so nothing repeats.
        // With notifications off the records are still marked, so turning
        // them back on never releases a backlog of stale alerts.
        if settings.notify.load(Ordering::Relaxed) {
            for view in &due {
                present(&app, view);
            }
        } else if !due.is_empty() {
            eprintln!("reminders: {} alert(s) skipped, calendar notifications are off", due.len());
        }

        let delay = {
            let guard = store.lock().unwrap_or_else(|p| p.into_inner());
            next_delay(&guard, unix_now())
        };
        match wake.recv_timeout(delay) {
            Ok(()) | Err(RecvTimeoutError::Timeout) => continue,
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }
}

/// Match the records to the calendar: new occurrences get a reminder, ones
/// that vanished (deleted, or moved, which changes the key) are cancelled,
/// and past ones are forgotten. Existing records keep their state, except
/// that a pending, unsnoozed alert follows the current lead time.
pub(crate) fn reconcile(store: &mut Store, events: &[CalendarEvent], now: i64, lead_secs: i64) -> bool {
    let mut changed = false;
    let mut seen: HashSet<String> = HashSet::new();

    for event in events {
        // All-day entries have no useful "starts in 10 minutes".
        if event.all_day || event.start_unix <= now {
            continue;
        }
        let id = event.id.clone().unwrap_or_else(|| event.title.clone());
        let candidate = Reminder::for_event(&id, &event.title, &event.start, event.start_unix, lead_secs);
        seen.insert(candidate.key.clone());
        match store.get_mut(&candidate.key) {
            Some(existing) => {
                if existing.title != event.title {
                    existing.title = event.title.clone();
                    changed = true;
                }
                if existing.pending() && existing.snoozed_until.is_none() && existing.remind_at != candidate.remind_at {
                    existing.remind_at = candidate.remind_at;
                    changed = true;
                }
            }
            None => {
                eprintln!("reminders: scheduled {} (alert at {})", candidate.key, candidate.remind_at);
                store.items.push(candidate);
                changed = true;
            }
        }
    }

    let before = store.items.len();
    store.items.retain(|r| {
        if r.start_unix <= now {
            return false; // over: nothing left to say
        }
        if r.event_id == DEMO_EVENT_ID {
            return true;
        }
        let in_window = r.start_unix - now <= HORIZON_SECS;
        if in_window && !seen.contains(&r.key) {
            eprintln!("reminders: cancelled {} (no longer on the calendar)", r.key);
            return false;
        }
        true
    });
    changed || store.items.len() != before
}

/// Mark every due reminder sent and return what to show. A reminder whose
/// event already started is marked sent silently: a late alert helps nobody.
pub(crate) fn take_due(store: &mut Store, now: i64) -> Vec<ReminderView> {
    let mut due = Vec::new();
    for reminder in store.items.iter_mut() {
        if !reminder.pending() || reminder.remind_at > now {
            continue;
        }
        reminder.sent = true;
        if reminder.start_unix > now {
            due.push(ReminderView::of(reminder, now));
        }
    }
    due
}

/// Sleep until the next alert, but never longer than the refresh interval.
pub(crate) fn next_delay(store: &Store, now: i64) -> Duration {
    let next = store
        .items
        .iter()
        .filter(|r| r.pending())
        .map(|r| r.remind_at - now)
        .min();
    let secs = next.map_or(REFRESH_SECS, |s| s.clamp(1, REFRESH_SECS));
    Duration::from_secs(secs as u64)
}

/// Native notification plus the in-app popup, for one reminder.
fn present(app: &AppHandle, view: &ReminderView) {
    let line = match view.minutes_until {
        m if m <= 0 => "Starting now".to_string(),
        1 => "Starts in 1 minute".to_string(),
        m => format!("Starts in {m} minutes"),
    };
    if let Err(err) = app
        .notification()
        .builder()
        .title("Dully")
        .body(format!("{}\n{line}", view.title))
        .show()
    {
        eprintln!("reminders: notification failed: {err}");
    }
    eprintln!("reminders: alerted {}", view.key);
    reveal(app, view);
}

/// Size the window for the popup, pin it visible, ask the poller to show it,
/// and hand the reminder to React.
fn reveal(app: &AppHandle, view: &ReminderView) {
    if let Err(err) = crate::commands::apply_reminder_open(app, true) {
        eprintln!("reminders: could not open the popup: {err}");
    }
    app.state::<VisibilityFlags>()
        .show_requested
        .store(true, Ordering::Relaxed);
    let _ = app.emit(FIRED_EVENT, view);
}

fn minutes_between(now: i64, later: i64) -> i64 {
    ((later - now) as f64 / 60.0).round() as i64
}

pub(crate) fn unix_now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Local ISO 8601 for a unix time, via the same formatter the calendar uses.
fn iso_local(unix: i64) -> String {
    #[cfg(target_os = "macos")]
    {
        crate::calendar::eventkit::iso_local(unix)
    }
    #[cfg(not(target_os = "macos"))]
    {
        format!("{unix}")
    }
}

fn log_save(result: std::io::Result<()>) {
    if let Err(err) = result {
        eprintln!("reminders: could not save state: {err}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::reminders::store::DEFAULT_LEAD_SECS as LEAD;

    fn event(id: &str, title: &str, start_unix: i64, all_day: bool) -> CalendarEvent {
        CalendarEvent {
            id: Some(id.into()),
            title: title.into(),
            start: format!("{start_unix}"),
            end: format!("{}", start_unix + 3600),
            start_unix,
            end_unix: start_unix + 3600,
            all_day,
            calendar_id: "c".into(),
            calendar_title: "Home".into(),
            location: None,
            notes: None,
        }
    }

    const NOW: i64 = 1_000_000;

    #[test]
    fn schedules_ten_minutes_before_and_keeps_state_on_refresh() {
        let mut store = Store::in_memory();
        let events = [event("a", "Project Meeting", NOW + 720, false)];
        assert!(reconcile(&mut store, &events, NOW, LEAD));
        assert_eq!(store.items.len(), 1);
        assert_eq!(store.items[0].remind_at, NOW + 720 - LEAD);

        store.items[0].sent = true;
        assert!(!reconcile(&mut store, &events, NOW + 60, LEAD), "unchanged calendar changes nothing");
        assert!(store.items[0].sent, "state survives a refresh");
    }

    #[test]
    fn skips_all_day_and_already_started_events() {
        let mut store = Store::in_memory();
        let events = [event("h", "Holiday", NOW + 3600, true), event("s", "Started", NOW - 60, false)];
        reconcile(&mut store, &events, NOW, LEAD);
        assert!(store.items.is_empty());
    }

    #[test]
    fn moved_event_gets_a_fresh_reminder_and_deleted_event_is_cancelled() {
        let mut store = Store::in_memory();
        reconcile(&mut store, &[event("a", "Meeting", NOW + 1800, false)], NOW, LEAD);
        store.items[0].dismissed = true;

        // Moved half an hour later: new key, new reminder, old one cancelled.
        reconcile(&mut store, &[event("a", "Meeting", NOW + 3600, false)], NOW, LEAD);
        assert_eq!(store.items.len(), 1);
        assert_eq!(store.items[0].start_unix, NOW + 3600);
        assert!(!store.items[0].dismissed);

        // Deleted: cancelled.
        reconcile(&mut store, &[], NOW, LEAD);
        assert!(store.items.is_empty());
    }

    #[test]
    fn recurring_occurrences_are_distinct() {
        let mut store = Store::in_memory();
        let events = [event("r", "Standup", NOW + 3600, false), event("r", "Standup", NOW + 7200, false)];
        reconcile(&mut store, &events, NOW, LEAD);
        assert_eq!(store.items.len(), 2);
    }

    #[test]
    fn fires_once_and_never_again() {
        let mut store = Store::in_memory();
        reconcile(&mut store, &[event("a", "Meeting", NOW + 600, false)], NOW, LEAD);
        assert!(take_due(&mut store, NOW - 1).is_empty(), "not due yet");
        let due = take_due(&mut store, NOW);
        assert_eq!(due.len(), 1);
        assert_eq!(due[0].minutes_until, 10);
        assert!(take_due(&mut store, NOW + 30).is_empty(), "a second pass does not repeat it");
        assert!(store.items[0].awaiting_user(NOW + 30));
    }

    #[test]
    fn late_reminder_is_swallowed_silently() {
        let mut store = Store::in_memory();
        // The app was closed; the event started 5 minutes ago.
        store.items.push(Reminder::for_event("a", "Meeting", "x", NOW - 300, LEAD));
        assert!(take_due(&mut store, NOW).is_empty());
        assert!(store.items[0].sent);
    }

    #[test]
    fn snooze_rearms_and_dismiss_ends_it() {
        let mut store = Store::in_memory();
        reconcile(&mut store, &[event("a", "Meeting", NOW + 600, false)], NOW, LEAD);
        take_due(&mut store, NOW);

        let r = store.get_mut("a@1000600").unwrap();
        r.snooze(5, NOW);
        assert_eq!(r.remind_at, NOW + 300);
        assert_eq!(r.snoozed_until, Some(NOW + 300));
        assert!(r.pending() && !r.awaiting_user(NOW), "popup closes until it fires again");
        assert!(take_due(&mut store, NOW + 299).is_empty());
        assert_eq!(take_due(&mut store, NOW + 300).len(), 1, "fires again after the snooze");

        let r = store.get_mut("a@1000600").unwrap();
        r.dismiss();
        assert!(!r.pending() && !r.awaiting_user(NOW + 301));
        r.snooze(5, NOW + 301); // a stale snooze after dismiss must not resurrect it
        assert!(take_due(&mut store, NOW + 700).is_empty());
    }

    #[test]
    fn changing_the_lead_moves_pending_alerts_but_not_snoozed_or_sent_ones() {
        let mut store = Store::in_memory();
        let events = [event("a", "A", NOW + 3600, false), event("b", "B", NOW + 3600, false), event("c", "C", NOW + 3600, false)];
        reconcile(&mut store, &events, NOW, LEAD);
        store.get_mut("b@1003600").unwrap().snooze(5, NOW);
        store.get_mut("c@1003600").unwrap().sent = true;

        assert!(reconcile(&mut store, &events, NOW, 30 * 60));
        assert_eq!(store.get_mut("a@1003600").unwrap().remind_at, NOW + 3600 - 1800, "pending follows the new lead");
        assert_eq!(store.get_mut("b@1003600").unwrap().remind_at, NOW + 300, "a snooze is kept");
        assert_eq!(store.get_mut("c@1003600").unwrap().remind_at, NOW + 3600 - LEAD, "an alert already sent stays put");
    }

    #[test]
    fn next_delay_targets_the_next_alert_within_the_refresh_cap() {
        let mut store = Store::in_memory();
        assert_eq!(next_delay(&store, NOW), Duration::from_secs(60));
        store.items.push(Reminder::for_event("a", "M", "x", NOW + 600 + 25, LEAD));
        assert_eq!(next_delay(&store, NOW), Duration::from_secs(25));
        store.items[0].sent = true;
        assert_eq!(next_delay(&store, NOW), Duration::from_secs(60));
    }
}
