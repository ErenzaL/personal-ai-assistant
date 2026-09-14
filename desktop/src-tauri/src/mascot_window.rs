//! Placement, sizing, and hit-testing of the floating mascot window.
//!
//! The window has two modes that share one bottom-right anchor:
//! - `Mascot`: a small square holding only the mascot.
//! - `Chat`:   a taller window with the chat panel above the mascot. The mascot
//!   keeps the same on-screen spot because the anchor is the bottom-right corner.

use tauri::{LogicalSize, PhysicalPosition, PhysicalSize, WebviewWindow};

/// Gap between the window's right edge and the right edge of the usable screen
/// area, in logical pixels.
const RIGHT_MARGIN: f64 = 80.0;

/// Gap between the window's bottom edge and the bottom of the usable screen
/// area (the top of the Dock), in logical pixels. The window itself has 12 px
/// of transparent padding, so the visible platform floats slightly above the Dock.
const BOTTOM_MARGIN: f64 = 0.0;

/// Window size in mascot-only mode. Must match `tauri.conf.json` and the
/// `.app__mascot` box in `styles.css`.
const MASCOT_SIZE: LogicalSize<f64> = LogicalSize {
    width: 170.0,
    height: 170.0,
};

/// Window size with the chat panel open. The panel gets everything above the
/// 170 px mascot box, minus the 12 px top padding: 558 px tall, 396 px wide.
const CHAT_SIZE: LogicalSize<f64> = LogicalSize {
    width: 420.0,
    height: 740.0,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Mascot,
    Chat,
}

impl Mode {
    fn size(self) -> LogicalSize<f64> {
        match self {
            Mode::Mascot => MASCOT_SIZE,
            Mode::Chat => CHAT_SIZE,
        }
    }
}

/// Resize the window for `mode` and keep its bottom-right corner anchored.
///
/// Tauri positions windows by their top-left corner, so growing the window would
/// otherwise push it down past the Dock. When growing we move first, then
/// resize; when shrinking we resize first, then move. Each order keeps the
/// intermediate frame inside the screen.
pub fn set_mode(window: &WebviewWindow, mode: Mode) -> tauri::Result<()> {
    let logical = mode.size();
    let physical: PhysicalSize<u32> = logical.to_physical(window.scale_factor()?);
    let position = resting_position_for(window, physical)?;

    match mode {
        Mode::Chat => {
            if let Some(position) = position {
                window.set_position(position)?;
            }
            window.set_size(logical)
        }
        Mode::Mascot => {
            window.set_size(logical)?;
            match position {
                Some(position) => window.set_position(position),
                None => Ok(()),
            }
        }
    }
}

/// Resting spot for a window of the given size: bottom-right of the work area
/// of the monitor it is on (falling back to the primary monitor). `None` if no
/// monitor is available.
pub fn resting_position_for(
    window: &WebviewWindow,
    size: PhysicalSize<u32>,
) -> tauri::Result<Option<PhysicalPosition<i32>>> {
    let monitor = match window.current_monitor()?.or(window.primary_monitor()?) {
        Some(monitor) => monitor,
        None => return Ok(None),
    };

    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let right_margin = (RIGHT_MARGIN * scale).round() as i32;
    let bottom_margin = (BOTTOM_MARGIN * scale).round() as i32;

    let x = area.position.x + area.size.width as i32 - size.width as i32 - right_margin;
    let y = area.position.y + area.size.height as i32 - size.height as i32 - bottom_margin;

    Ok(Some(PhysicalPosition::new(x, y)))
}

/// Resting spot for the window at its current size.
pub fn resting_position(window: &WebviewWindow) -> tauri::Result<Option<PhysicalPosition<i32>>> {
    resting_position_for(window, window.outer_size()?)
}

/// Move the window to its resting spot. No-op if no monitor can be determined.
pub fn place_at_rest(window: &WebviewWindow) -> tauri::Result<()> {
    match resting_position(window)? {
        Some(position) => window.set_position(position),
        None => Ok(()),
    }
}

/// True when `cursor` (global physical pixels) lies inside the window's outer
/// rectangle grown by `slack` logical pixels on every side.
///
/// The slack lets a cursor sitting just outside the window, for example in the
/// gap between the Dock and the mascot, still count as "over" it. Returns false
/// if the window geometry cannot be read.
pub fn is_cursor_over(window: &WebviewWindow, cursor: PhysicalPosition<f64>, slack: f64) -> bool {
    let (Ok(position), Ok(size), Ok(scale)) = (
        window.outer_position(),
        window.outer_size(),
        window.scale_factor(),
    ) else {
        return false;
    };
    let slack = slack * scale;

    let left = position.x as f64 - slack;
    let top = position.y as f64 - slack;
    let right = position.x as f64 + size.width as f64 + slack;
    let bottom = position.y as f64 + size.height as f64 + slack;

    cursor.x >= left && cursor.x <= right && cursor.y >= top && cursor.y <= bottom
}
