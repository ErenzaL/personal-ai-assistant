//! Reminder records and their file.

use std::fs;
use std::io;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

/// Alert this long before an event starts, until the settings say otherwise.
pub const DEFAULT_LEAD_SECS: i64 = 10 * 60;

/// Marker id for the `--demo-reminder` flag: never pruned as "gone from the
/// calendar", because it was never in it.
pub const DEMO_EVENT_ID: &str = "demo";

/// One logical reminder for one event occurrence.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Reminder {
    /// `<event id>@<start unix>`. Recurring events share an id, so the start
    /// is part of the key; an event that moves gets a fresh reminder.
    pub key: String,
    pub event_id: String,
    pub title: String,
    /// Event start, ISO 8601 with the local offset, for display.
    pub start: String,
    pub start_unix: i64,
    /// When to alert: the start minus the lead, or `snoozed_until` after a snooze.
    pub remind_at: i64,
    /// The alert for `remind_at` has gone out. Set before it is shown, and
    /// saved, so a crash or restart cannot repeat it.
    pub sent: bool,
    pub snoozed_until: Option<i64>,
    pub dismissed: bool,
}

impl Reminder {
    pub fn for_event(event_id: &str, title: &str, start: &str, start_unix: i64, lead_secs: i64) -> Self {
        Self {
            key: format!("{event_id}@{start_unix}"),
            event_id: event_id.to_string(),
            title: title.to_string(),
            start: start.to_string(),
            start_unix,
            remind_at: start_unix - lead_secs,
            sent: false,
            snoozed_until: None,
            dismissed: false,
        }
    }

    /// Still has an alert to send.
    pub fn pending(&self) -> bool {
        !self.dismissed && !self.sent
    }

    /// Alerted and waiting for the user to snooze or dismiss.
    pub fn awaiting_user(&self, now: i64) -> bool {
        self.sent && !self.dismissed && self.start_unix > now
    }

    pub fn snooze(&mut self, minutes: i64, now: i64) {
        let until = now + minutes.clamp(1, 24 * 60) * 60;
        self.snoozed_until = Some(until);
        self.remind_at = until;
        self.sent = false;
    }

    pub fn dismiss(&mut self) {
        self.dismissed = true;
    }
}

#[derive(Default, Serialize, Deserialize)]
struct FileFormat {
    version: u32,
    reminders: Vec<Reminder>,
}

/// The records plus where they live on disk.
pub struct Store {
    path: PathBuf,
    pub items: Vec<Reminder>,
}

impl Store {
    /// Read the file; a missing or unreadable file is an empty store.
    pub fn load(path: PathBuf) -> Self {
        let items = fs::read(&path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<FileFormat>(&bytes).ok())
            .map(|file| file.reminders)
            .unwrap_or_default();
        Self { path, items }
    }

    /// Write atomically: a temp file, then a rename.
    pub fn save(&self) -> io::Result<()> {
        if let Some(dir) = self.path.parent() {
            fs::create_dir_all(dir)?;
        }
        let file = FileFormat {
            version: 1,
            reminders: self.items.clone(),
        };
        let tmp = self.path.with_extension("json.tmp");
        fs::write(&tmp, serde_json::to_vec_pretty(&file)?)?;
        fs::rename(&tmp, &self.path)
    }

    pub fn get_mut(&mut self, key: &str) -> Option<&mut Reminder> {
        self.items.iter_mut().find(|r| r.key == key)
    }

    #[cfg(test)]
    pub fn in_memory() -> Self {
        Self {
            path: PathBuf::from("/dev/null"),
            items: Vec::new(),
        }
    }
}
