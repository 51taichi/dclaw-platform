use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use clipboard_rs::{common::RustImage, Clipboard, ClipboardContext, ContentFormat};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, State,
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
const LOCAL_HELPER_HEARTBEAT_MAX_AGE_SECONDS: u64 = 45;

#[derive(Default)]
struct LocalHelperProcessState {
    child: Mutex<Option<Child>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LocalHelperStartRequest {
    server_websocket_uri: String,
    pairing_code: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LocalHelperStatus {
    supported: bool,
    installed: bool,
    running: bool,
    connected: bool,
    paired: bool,
    device_id: Option<String>,
    runner_version: &'static str,
}

fn local_helper_directory(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map(|path| path.join("local-helper"))
        .map_err(|error| format!("无法确定本地助手配置目录: {error}"))
}

fn local_helper_executable(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(configured) = std::env::var_os("DCLAW_LOCAL_HELPER_EXECUTABLE") {
        return Ok(PathBuf::from(configured));
    }
    app.path()
        .resource_dir()
        .map(|path| {
            path.join("resources")
                .join("local-helper")
                .join("DClaw.LocalHelper.exe")
        })
        .map_err(|error| format!("无法确定本地助手程序目录: {error}"))
}

fn local_helper_runtime_status_path(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        return Ok(PathBuf::from(local_app_data)
            .join("DClawLocalTool")
            .join("helper-status.json"));
    }
    Ok(local_helper_directory(app)?
        .join("runtime")
        .join("helper-status.json"))
}

fn read_json(path: &Path) -> Option<Value> {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
}

fn fresh_runtime_status(path: &Path) -> Option<Value> {
    let value = read_json(path)?;
    let heartbeat = value.get("heartbeatUnixSeconds")?.as_u64()?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    (now.saturating_sub(heartbeat) <= LOCAL_HELPER_HEARTBEAT_MAX_AGE_SECONDS).then_some(value)
}

fn configured_device_id(config_path: &Path) -> Option<String> {
    read_json(config_path)?
        .get("deviceId")?
        .as_str()
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
}

fn config_has_device_token(config_path: &Path) -> bool {
    read_json(config_path)
        .and_then(|value| {
            value
                .get("deviceToken")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .is_some_and(|value| !value.is_empty())
}

fn local_helper_status_value(app: &AppHandle) -> Result<LocalHelperStatus, String> {
    let supported = cfg!(target_os = "windows");
    let executable = local_helper_executable(app)?;
    let config_path = local_helper_directory(app)?.join("config.json");
    let runtime = fresh_runtime_status(&local_helper_runtime_status_path(app)?);
    let running = runtime.is_some();
    let connected = runtime
        .as_ref()
        .and_then(|value| value.get("connected"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let device_id = runtime
        .as_ref()
        .and_then(|value| value.get("deviceId"))
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .or_else(|| configured_device_id(&config_path));
    Ok(LocalHelperStatus {
        supported,
        installed: executable.is_file(),
        running,
        connected,
        paired: device_id.is_some() && config_has_device_token(&config_path),
        device_id,
        runner_version: "1.0.0",
    })
}

#[tauri::command]
fn get_local_helper_status(
    app: AppHandle,
    state: State<'_, LocalHelperProcessState>,
) -> Result<LocalHelperStatus, String> {
    let mut status = local_helper_status_value(&app)?;
    let mut process = state
        .child
        .lock()
        .map_err(|_| "本地助手进程状态不可用".to_owned())?;
    if let Some(child) = process.as_mut() {
        match child.try_wait() {
            Ok(None) => status.running = true,
            Ok(Some(_)) => *process = None,
            Err(_) => *process = None,
        }
    }
    Ok(status)
}

fn stop_local_helper_process(
    app: &AppHandle,
    state: &LocalHelperProcessState,
) -> Result<(), String> {
    if let Some(mut child) = state
        .child
        .lock()
        .map_err(|_| "本地助手进程状态不可用".to_owned())?
        .take()
    {
        let _ = child.kill();
        let _ = child.wait();
    }

    let status_path = local_helper_runtime_status_path(app)?;
    if let Some(pid) = fresh_runtime_status(&status_path)
        .and_then(|value| value.get("pid").and_then(Value::as_u64))
    {
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            let _ = Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(0x08000000)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
        #[cfg(not(target_os = "windows"))]
        let _ = pid;
    }
    let _ = fs::remove_file(status_path);
    Ok(())
}

#[tauri::command]
fn stop_local_helper(
    app: AppHandle,
    state: State<'_, LocalHelperProcessState>,
) -> Result<(), String> {
    stop_local_helper_process(&app, &state)
}

#[tauri::command]
fn start_local_helper(
    app: AppHandle,
    state: State<'_, LocalHelperProcessState>,
    request: LocalHelperStartRequest,
) -> Result<LocalHelperStatus, String> {
    if !cfg!(target_os = "windows") {
        return local_helper_status_value(&app);
    }
    let executable = local_helper_executable(&app)?;
    if !executable.is_file() {
        return Err("当前 DClaw 安装包未包含通用本地助手，请升级客户端。".to_owned());
    }

    let helper_directory = local_helper_directory(&app)?;
    fs::create_dir_all(&helper_directory)
        .map_err(|error| format!("无法创建本地助手配置目录: {error}"))?;
    let config_path = helper_directory.join("config.json");
    let existing = read_json(&config_path).unwrap_or_else(|| json!({}));
    let pairing = request
        .pairing_code
        .as_deref()
        .filter(|value| !value.is_empty());
    if pairing.is_some() {
        stop_local_helper_process(&app, &state)?;
    } else if local_helper_status_value(&app)?.running {
        return local_helper_status_value(&app);
    }

    let config = json!({
        "serverWebSocketUri": request.server_websocket_uri,
        "deviceId": if pairing.is_some() {
            ""
        } else {
            existing.get("deviceId").and_then(Value::as_str).unwrap_or("")
        },
        "deviceToken": if pairing.is_some() {
            Value::Null
        } else {
            existing.get("deviceToken").cloned().unwrap_or(Value::Null)
        },
        "pairingCode": pairing,
        "displayName": std::env::var("COMPUTERNAME")
            .unwrap_or_else(|_| "Windows device".to_owned()),
        "runnerVersion": "1.0.0",
        "protocolVersion": "1",
    });
    fs::write(
        &config_path,
        serde_json::to_vec_pretty(&config)
            .map_err(|error| format!("无法生成本地助手配置: {error}"))?,
    )
    .map_err(|error| format!("无法写入本地助手配置: {error}"))?;

    let mut command = Command::new(executable);
    command
        .arg(&config_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let child = command
        .spawn()
        .map_err(|error| format!("无法启动本地助手: {error}"))?;
    *state
        .child
        .lock()
        .map_err(|_| "本地助手进程状态不可用".to_owned())? = Some(child);
    let mut status = local_helper_status_value(&app)?;
    status.running = true;
    Ok(status)
}

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
        .manage(LocalHelperProcessState::default())
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
            read_clipboard_attachments,
            get_local_helper_status,
            start_local_helper,
            stop_local_helper
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
    use super::{attachments_from_paths, close_action, config_has_device_token, CloseAction};
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

    #[test]
    fn local_helper_pairing_requires_a_persisted_device_token() {
        let unique = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("dclaw-helper-config-{unique}.json"));
        fs::write(&path, r#"{"deviceId":"device-1","deviceToken":null}"#).unwrap();
        assert!(!config_has_device_token(&path));
        fs::write(&path, r#"{"deviceId":"device-1","deviceToken":"secret"}"#).unwrap();
        assert!(config_has_device_token(&path));
        fs::remove_file(path).unwrap();
    }
}
