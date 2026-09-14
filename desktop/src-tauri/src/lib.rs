mod activation;
mod commands;
mod mascot_window;
mod platform;
mod tray;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // The app runs as an accessory (no Dock icon, no menu bar). This is what
    // lets the mascot float over other apps' full-screen Spaces, and macOS
    // only honours it for windows created while the policy is already in
    // effect, so it is applied before Tauri builds anything.
    platform::become_accessory_app();

    #[allow(unused_mut)]
    let mut app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![commands::set_chat_open])
        .setup(|app| {
            let window = app
                .get_webview_window("main")
                .expect("main window is declared in tauri.conf.json");

            // Park the window at its resting spot but keep it hidden. The
            // activation poller shows it when the cursor hits the screen edge.
            platform::allow_over_fullscreen(&window)?;
            mascot_window::place_at_rest(&window)?;
            activation::start(app.handle().clone());
            tray::build(app)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Tell Tauri's event loop the same policy *before* it launches. Otherwise
    // it applies its default (Regular) at launch and flips the app back.
    #[cfg(target_os = "macos")]
    app.set_activation_policy(tauri::ActivationPolicy::Accessory);

    app.run(|_app, _event| {});
}
