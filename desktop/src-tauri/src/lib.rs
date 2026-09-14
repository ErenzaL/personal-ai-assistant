mod activation;
mod backend;
mod calendar;
mod commands;
mod mascot_window;
mod platform;
mod reminders;
mod tray;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Support diagnostic: `--list-calendars` prints what EventKit reports and
    // exits. Runs inside the app bundle, so it uses the same calendar
    // permission the app itself holds.
    if let Some(range) = std::env::args().position(|a| a == "--list-events") {
        let args: Vec<String> = std::env::args().collect();
        let start = args.get(range + 1).cloned().unwrap_or_default();
        let end = args.get(range + 2).cloned().unwrap_or_default();
        let bridge = calendar::CalendarBridge::spawn(Box::new(|| {}));
        let output = bridge
            .handle()
            .and_then(|h| {
                if !h.authorization_status()?.grants_read() {
                    h.request_access()?;
                }
                h.list_events(start, end, None)
            })
            .map(|e| serde_json::to_string_pretty(&e).unwrap_or_default())
            .unwrap_or_else(|e| serde_json::to_string_pretty(&e).unwrap_or_default());
        println!("{output}");
        return;
    }

    // Support diagnostic: `--login-item status|on|off` prints what macOS
    // reports for this bundle's login item and exits.
    #[cfg(target_os = "macos")]
    if let Some(at) = std::env::args().position(|a| a == "--login-item") {
        let action = std::env::args().nth(at + 1).unwrap_or_else(|| "status".into());
        println!("{}", platform::login_item_diagnostic(&action));
        return;
    }

    if std::env::args().any(|a| a == "--list-calendars") {
        let bridge = calendar::CalendarBridge::spawn(Box::new(|| {}));
        let output = bridge
            .handle()
            .and_then(|h| {
                // Ask first if we have never been asked, so the diagnostic is
                // usable on a fresh build.
                if !h.authorization_status()?.grants_read() {
                    h.request_access()?;
                }
                h.list_calendars()
            })
            .map(|c| serde_json::to_string_pretty(&c).unwrap_or_default())
            .unwrap_or_else(|e| serde_json::to_string_pretty(&e).unwrap_or_default());
        println!("{output}");
        return;
    }

    // The app runs as an accessory (no Dock icon, no menu bar). This is what
    // lets the mascot float over other apps' full-screen Spaces, and macOS
    // only honours it for windows created while the policy is already in
    // effect, so it is applied before Tauri builds anything.
    platform::become_accessory_app();

    #[allow(unused_mut)]
    let mut app = tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            commands::set_chat_open,
            commands::apply_settings,
            backend::backend_url,
            commands::login_item_status,
            commands::set_login_item,
            reminders::commands::reminder_active,
            reminders::commands::reminder_snooze,
            reminders::commands::reminder_dismiss,
            calendar::commands::calendar_get_authorization_status,
            calendar::commands::calendar_request_access,
            calendar::commands::calendar_list_calendars,
            calendar::commands::calendar_list_events,
            calendar::commands::calendar_create_event,
            calendar::commands::calendar_open_settings,
        ])
        .setup(|app| {
            let window = app
                .get_webview_window("main")
                .expect("main window is declared in tauri.conf.json");

            // One EventKit store, owned by its own thread for the life of
            // the app. Creating it does not prompt for permission. Calendar
            // changes wake the reminder thread; the channel holds one pending
            // wake-up, so a burst of changes costs a single pass.
            let (wake_tx, wake_rx) = std::sync::mpsc::sync_channel::<()>(1);
            let on_change = wake_tx.clone();
            let bridge = calendar::CalendarBridge::spawn(Box::new(move || {
                let _ = on_change.try_send(());
            }));
            let calendar_handle = bridge.handle().map_err(|e| e.message)?;
            app.manage(bridge);

            // Park the window at its resting spot but keep it hidden. The
            // activation poller shows it when the cursor hits the screen edge.
            platform::allow_over_fullscreen(&window)?;
            mascot_window::place_at_rest(&window)?;
            activation::start(app.handle().clone());
            tray::build(app)?;

            // Reminders: load what was pending, then keep watching the calendar.
            let reminders = reminders::Reminders::start(
                app.handle().clone(),
                calendar_handle.clone(),
                wake_tx,
                wake_rx,
            );
            // `--demo-reminder`: a fake "Project Meeting" in 11 minutes whose
            // alert is due now, to try the whole flow without a real event.
            if std::env::args().any(|a| a == "--demo-reminder") {
                reminders.add_demo(11);
            }
            reminders.restore_popup();
            app.manage(reminders);

            // Calendar permission: use it when granted, ask once when macOS
            // has never asked, and otherwise leave it to Settings, which
            // explains the state and opens System Settings. Nothing is stored.
            let calendar_for_prompt = calendar_handle.clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(2));
                if let Ok(calendar::types::AuthorizationStatus::NotDetermined) =
                    calendar_for_prompt.authorization_status()
                {
                    let _ = calendar_for_prompt.request_access();
                }
            });

            // The local backend, started here unless one is already running.
            app.manage(backend::Backend::start(app.handle().clone()));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Tell Tauri's event loop the same policy *before* it launches. Otherwise
    // it applies its default (Regular) at launch and flips the app back.
    #[cfg(target_os = "macos")]
    app.set_activation_policy(tauri::ActivationPolicy::Accessory);

    app.run(|app, event| {
        // Quit from the tray (or any exit) takes the backend we started with it.
        if let tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit = event {
            if let Some(backend) = app.try_state::<backend::Backend>() {
                backend.stop();
            }
        }
    });
}
