//! Menu bar (tray) icon.
//!
//! The app runs as an accessory (no Dock icon, no menu bar), which is what lets
//! the mascot float over other apps' full-screen Spaces. That also removes the
//! usual Cmd+Q, so the tray menu is the way to quit.

use std::sync::atomic::Ordering;

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{App, Manager};

use crate::activation::VisibilityFlags;

const ICON: &[u8] = include_bytes!("../icons/tray.png");

pub fn build(app: &App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show assistant", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, Some("CmdOrCtrl+Q"))?;
    let menu = Menu::with_items(app, &[&show, &quit])?;

    TrayIconBuilder::with_id("main")
        .icon(Image::from_bytes(ICON)?)
        .tooltip("Personal AI Assistant")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                // Ask the activation poller to show the mascot; it owns the
                // window's visibility state so both paths stay consistent.
                app.state::<VisibilityFlags>()
                    .show_requested
                    .store(true, Ordering::Relaxed);
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}
