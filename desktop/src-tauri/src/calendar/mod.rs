//! Calendar access through Apple's EventKit.
//!
//! React -> Tauri commands -> EventKit -> the macOS Calendar database, which
//! already aggregates iCloud, Google and any other account configured in
//! System Settings. No OAuth, no passwords, and nothing here goes through the
//! Python backend.
//!
//! This step covers authorization only; listing and creating events come next.

pub mod commands;
pub mod eventkit;
pub mod types;

pub use eventkit::CalendarBridge;
