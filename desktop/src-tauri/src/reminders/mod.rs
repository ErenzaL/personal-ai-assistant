//! Upcoming-event reminders.
//!
//! One background thread, no model, no backend: it reads upcoming events from
//! the EventKit bridge, keeps one record per occurrence in a small JSON file,
//! and when a record comes due it sends a native notification *and* tells the
//! React side to show the in-app popup. Both come from the same record, so
//! there is never a second, separate alert. Snooze and dismiss act on that
//! record too, and the file survives restarts.

pub mod commands;
mod service;
mod store;

pub use service::{Reminders, ReminderView};
