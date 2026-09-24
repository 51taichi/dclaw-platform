use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogResult};

#[derive(Debug, PartialEq, Eq)]
enum CloseAction {
    HideToTray,
    Quit,
    KeepOpen,
}

fn close_action(result: &MessageDialogResult) -> CloseAction {
    match result {
        MessageDialogResult::Custom(label) if label == "后台运行" => CloseAction::HideToTray,
        MessageDialogResult::Custom(label) if label == "退出程序" => CloseAction::Quit,
        _ => CloseAction::KeepOpen,
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .setup(|app| {
            // ── Logging (debug only) ─────────────────────────────────
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // ── System Tray ──────────────────────────────────────────
            let show = MenuItem::with_id(app, "show", "显示 DClaw", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "隐藏窗口", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[&show, &hide, &quit])?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("DClaw - AI 智能工作台")
                .on_menu_event(move |app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                                let _ = window.unminimize();
                            }
                        }
                        "hide" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.hide();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.unminimize();
                        }
                    }
                })
                .build(app)?;

            // ── Ask whether to keep running or quit ─────────────────
            let main_window = app.get_webview_window("main").unwrap();
            let close_window = main_window.clone();
            let close_dialog_open = Arc::new(AtomicBool::new(false));
            main_window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    if close_dialog_open.swap(true, Ordering::SeqCst) {
                        return;
                    }

                    let dialog_window = close_window.clone();
                    let dialog_open = close_dialog_open.clone();
                    close_window
                        .app_handle()
                        .dialog()
                        .message("是否让 AI超级专家 继续在后台运行？")
                        .title("关闭 AI超级专家")
                        .buttons(MessageDialogButtons::YesNoCancelCustom(
                            "后台运行".into(),
                            "退出程序".into(),
                            "取消".into(),
                        ))
                        .show_with_result(move |result| {
                            dialog_open.store(false, Ordering::SeqCst);
                            match close_action(&result) {
                                CloseAction::HideToTray => {
                                    let _ = dialog_window.hide();
                                }
                                CloseAction::Quit => dialog_window.app_handle().exit(0),
                                CloseAction::KeepOpen => {}
                            }
                        });
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_app_status])
        .run(tauri::generate_context!())
        .expect("error while running DClaw");
}

/// Get current application status for the frontend status bar
#[tauri::command]
fn get_app_status() -> serde_json::Value {
    serde_json::json!({
        "status": "running",
        "version": env!("CARGO_PKG_VERSION"),
        "platform": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
    })
}

#[cfg(test)]
mod tests {
    use super::{close_action, CloseAction};
    use tauri_plugin_dialog::MessageDialogResult;

    #[test]
    fn close_dialog_choice_maps_to_expected_action() {
        assert_eq!(
            close_action(&MessageDialogResult::Custom("后台运行".into())),
            CloseAction::HideToTray
        );
        assert_eq!(
            close_action(&MessageDialogResult::Custom("退出程序".into())),
            CloseAction::Quit
        );
        assert_eq!(
            close_action(&MessageDialogResult::Cancel),
            CloseAction::KeepOpen
        );
    }
}
