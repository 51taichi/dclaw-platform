use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use clipboard_rs::{common::RustImage, Clipboard, ClipboardContext, ContentFormat};
use serde::Serialize;
use std::path::{Path, PathBuf};
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

const CHAT_ATTACHMENT_MAX_BYTES: u64 = 25 * 1024 * 1024;
const CLIPBOARD_ATTACHMENT_LIMIT: usize = 20;

#[derive(Debug, Serialize)]
struct ClipboardAttachment {
    name: String,
    mime_type: String,
    base64_data: String,
}

fn attachment_from_bytes(
    name: String,
    mime_type: String,
    bytes: Vec<u8>,
) -> Option<ClipboardAttachment> {
    if bytes.is_empty() || bytes.len() as u64 > CHAT_ATTACHMENT_MAX_BYTES {
        return None;
    }
    Some(ClipboardAttachment {
        name,
        mime_type,
        base64_data: BASE64.encode(bytes),
    })
}

fn attachment_from_path(path: &Path) -> Result<Option<ClipboardAttachment>, String> {
    let metadata = std::fs::metadata(path)
        .map_err(|error| format!("无法读取剪切板文件 {}: {error}", path.display()))?;
    if !metadata.is_file() || metadata.len() > CHAT_ATTACHMENT_MAX_BYTES {
        return Ok(None);
    }

    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("剪切板文件名无效: {}", path.display()))?
        .to_owned();
    let bytes = std::fs::read(path)
        .map_err(|error| format!("无法读取剪切板文件 {}: {error}", path.display()))?;
    let mime_type = mime_guess::from_path(path)
        .first_or_octet_stream()
        .essence_str()
        .to_owned();
    Ok(attachment_from_bytes(name, mime_type, bytes))
}

fn attachments_from_paths(paths: &[PathBuf]) -> Result<Vec<ClipboardAttachment>, String> {
    paths
        .iter()
        .take(CLIPBOARD_ATTACHMENT_LIMIT)
        .filter_map(|path| match attachment_from_path(path) {
            Ok(Some(attachment)) => Some(Ok(attachment)),
            Ok(None) => None,
            Err(error) => Some(Err(error)),
        })
        .collect()
}

fn read_clipboard_attachments_blocking() -> Result<Vec<ClipboardAttachment>, String> {
    let clipboard =
        ClipboardContext::new().map_err(|error| format!("无法访问系统剪切板: {error}"))?;
    let paths = clipboard
        .get_files()
        .unwrap_or_default()
        .into_iter()
        .map(PathBuf::from)
        .collect::<Vec<_>>();
    let files = attachments_from_paths(&paths)?;
    if !files.is_empty() {
        return Ok(files);
    }

    if !clipboard.has(ContentFormat::Image) {
        return Ok(Vec::new());
    }
    let png = clipboard
        .get_image()
        .and_then(|image| image.to_png())
        .map_err(|error| format!("无法读取剪切板图片: {error}"))?;
    Ok(attachment_from_bytes(
        "clipboard.png".to_owned(),
        "image/png".to_owned(),
        png.get_bytes().to_vec(),
    )
    .into_iter()
    .collect())
}

#[tauri::command]
async fn read_clipboard_attachments() -> Result<Vec<ClipboardAttachment>, String> {
    tauri::async_runtime::spawn_blocking(read_clipboard_attachments_blocking)
        .await
        .map_err(|error| format!("读取剪切板任务失败: {error}"))?
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
        .plugin(tauri_plugin_fs::init())
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
                .on_menu_event(move |app, event| match event.id.as_ref() {
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
        .invoke_handler(tauri::generate_handler![
            get_app_status,
            read_clipboard_attachments
        ])
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
    use super::{attachments_from_paths, close_action, CloseAction};
    use std::{fs, time::SystemTime};
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

    #[test]
    fn clipboard_paths_become_bounded_upload_payloads() {
        let unique = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!("dclaw-clipboard-{unique}"));
        fs::create_dir_all(&directory).unwrap();
        let document = directory.join("客户资料.pdf");
        fs::write(&document, b"pdf").unwrap();

        let attachments = attachments_from_paths(&[document]).unwrap();

        assert_eq!(attachments.len(), 1);
        assert_eq!(attachments[0].name, "客户资料.pdf");
        assert_eq!(attachments[0].mime_type, "application/pdf");
        assert_eq!(attachments[0].base64_data, "cGRm");
        fs::remove_dir_all(directory).unwrap();
    }
}
