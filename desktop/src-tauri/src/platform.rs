//! Thin OS-specific helpers. Everything here has a no-op fallback so the crate
//! still builds on other platforms.

use tauri::WebviewWindow;

/// Switch the process to the *accessory* activation policy (no Dock icon, no
/// menu bar) before any window exists.
///
/// This must happen before Tauri creates the mascot window. macOS decides at
/// window creation whether a window may join other apps' full-screen Spaces,
/// and windows created while the app is a regular app are excluded for good;
/// switching the policy afterwards (or re-applying window flags) does not
/// repair them. Verified empirically on macOS 26.
///
/// Must be called on the main thread, i.e. at the very start of `run()`.
#[cfg(target_os = "macos")]
pub fn become_accessory_app() {
    use objc2::MainThreadMarker;
    use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy};

    let mtm = MainThreadMarker::new().expect("become_accessory_app must run on the main thread");
    NSApplication::sharedApplication(mtm).setActivationPolicy(NSApplicationActivationPolicy::Accessory);
}

#[cfg(not(target_os = "macos"))]
pub fn become_accessory_app() {}

/// Process id of the application that currently owns the menu bar, or `None`
/// if it cannot be determined.
///
/// macOS: `NSWorkspace.frontmostApplication`. Safe to call from any thread and
/// needs no permissions.
#[cfg(target_os = "macos")]
pub fn frontmost_app_pid() -> Option<i32> {
    use objc2_app_kit::NSWorkspace;

    let app = NSWorkspace::sharedWorkspace().frontmostApplication()?;
    Some(app.processIdentifier())
}

#[cfg(not(target_os = "macos"))]
pub fn frontmost_app_pid() -> Option<i32> {
    None
}

/// Let the window float over other apps' full-screen Spaces.
///
/// macOS keeps each full-screen app in its own Space, and ordinary windows,
/// even always-on-top ones, never appear there. Two NSWindow settings change
/// that, and Tauri exposes neither directly:
/// - `collectionBehavior` gains `FullScreenAuxiliary` (alongside
///   `CanJoinAllSpaces`, which `visibleOnAllWorkspaces` already sets).
/// - `level` is raised to `NSStatusWindowLevel`, above the level Tauri uses
///   for `alwaysOnTop`, so the window is not hidden behind the full-screen app.
///
/// Must be called on the main thread (Tauri's `setup` hook qualifies).
/// Note: activating the app (e.g. focusing the chat input) still switches
/// macOS back to the desktop Space; only a non-activating window stays.
#[cfg(target_os = "macos")]
pub fn allow_over_fullscreen(window: &WebviewWindow) -> tauri::Result<()> {
    use objc2_app_kit::{NSStatusWindowLevel, NSWindow, NSWindowCollectionBehavior};

    let ptr = window.ns_window()?;
    // SAFETY: `ns_window()` returns the live NSWindow backing this Tauri window,
    // which outlives this call, and we are on the main thread.
    let ns_window = unsafe { &*(ptr as *const NSWindow) };

    let behavior = ns_window.collectionBehavior()
        | NSWindowCollectionBehavior::CanJoinAllSpaces
        | NSWindowCollectionBehavior::FullScreenAuxiliary;
    ns_window.setCollectionBehavior(behavior);
    ns_window.setLevel(NSStatusWindowLevel);
    Ok(())
}

#[cfg(not(target_os = "macos"))]
pub fn allow_over_fullscreen(_window: &WebviewWindow) -> tauri::Result<()> {
    Ok(())
}

/// Human-readable level and collection behavior of the window, for debug logs.
#[cfg(target_os = "macos")]
pub fn describe_window(window: &WebviewWindow) -> String {
    use objc2_app_kit::NSWindow;
    match window.ns_window() {
        Ok(ptr) => {
            // SAFETY: same as `allow_over_fullscreen`.
            let ns_window = unsafe { &*(ptr as *const NSWindow) };
            format!(
                "level={} behavior={:#x} visible={} onActiveSpace={}",
                ns_window.level(),
                ns_window.collectionBehavior().0,
                ns_window.isVisible(),
                ns_window.isOnActiveSpace()
            )
        }
        Err(err) => format!("ns_window unavailable: {err}"),
    }
}

#[cfg(not(target_os = "macos"))]
pub fn describe_window(_window: &WebviewWindow) -> String {
    String::new()
}
