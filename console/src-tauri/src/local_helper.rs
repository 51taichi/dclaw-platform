use reqwest::{header::AUTHORIZATION, Url};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager, State};

const HEARTBEAT_MAX_AGE_SECONDS: u64 = 45;
const MAX_HELPER_BYTES: u64 = 256 * 1024 * 1024;
const DOWNLOAD_PATH_SUFFIX: &str = "/api/super-agent-support/local-helper/download";

#[derive(Default)]
pub(crate) struct LocalHelperProcessState {
    child: Mutex<Option<Child>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalHelperInstallRequest {
    download_url: String,
    server_origin: String,
    authorization: Option<String>,
    version: String,
    protocol_version: String,
    sha256: String,
    size_bytes: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalHelperStartRequest {
    server_websocket_uri: String,
    pairing_code: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct InstalledHelper {
    version: String,
    protocol_version: String,
    sha256: String,
    size_bytes: u64,
    executable: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalHelperStatus {
    supported: bool,
    installed: bool,
    running: bool,
    connected: bool,
    paired: bool,
    device_id: Option<String>,
    runner_version: String,
}

fn local_helper_directory(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map(|path| path.join("local-helper"))
        .map_err(|error| format!("无法确定本地助手配置目录: {error}"))
}

fn current_pointer_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(local_helper_directory(app)?.join("current.json"))
}

fn previous_pointer_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(local_helper_directory(app)?.join("previous.json"))
}

fn read_json(path: &Path) -> Option<Value> {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
}

fn read_installed_helper(path: &Path) -> Option<InstalledHelper> {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
}

fn safe_relative_path(value: &str) -> bool {
    !value.is_empty()
        && Path::new(value)
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn installed_helper(app: &AppHandle) -> Result<Option<(InstalledHelper, PathBuf)>, String> {
    if let Some(configured) = std::env::var_os("DCLAW_LOCAL_HELPER_EXECUTABLE") {
        let path = PathBuf::from(configured);
        return Ok(path.is_file().then_some((
            InstalledHelper {
                version: "external".to_owned(),
                protocol_version: "external".to_owned(),
                sha256: String::new(),
                size_bytes: fs::metadata(&path).map(|item| item.len()).unwrap_or(0),
                executable: path.to_string_lossy().into_owned(),
            },
            path,
        )));
    }
    let root = local_helper_directory(app)?;
    let Some(metadata) = read_installed_helper(&current_pointer_path(app)?) else {
        return Ok(None);
    };
    if !safe_relative_path(&metadata.executable) {
        return Ok(None);
    }
    let executable = root.join(&metadata.executable);
    if !executable.is_file() {
        return Ok(None);
    }
    Ok(Some((metadata, executable)))
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

fn fresh_runtime_status(path: &Path) -> Option<Value> {
    let value = read_json(path)?;
    let heartbeat = value.get("heartbeatUnixSeconds")?.as_u64()?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    (now.saturating_sub(heartbeat) <= HEARTBEAT_MAX_AGE_SECONDS).then_some(value)
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
    let installed = installed_helper(app)?;
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
        installed: installed.is_some(),
        running,
        connected,
        paired: device_id.is_some() && config_has_device_token(&config_path),
        device_id,
        runner_version: installed
            .map(|(metadata, _)| metadata.version)
            .unwrap_or_default(),
    })
}

#[tauri::command]
pub(crate) fn get_local_helper_status(
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
            Ok(Some(_)) | Err(_) => *process = None,
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
pub(crate) fn stop_local_helper(
    app: AppHandle,
    state: State<'_, LocalHelperProcessState>,
) -> Result<(), String> {
    stop_local_helper_process(&app, &state)
}

fn valid_version(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._+-".contains(&byte))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn validate_download_url(download: &str, server_origin: &str) -> Result<Url, String> {
    let url = Url::parse(download).map_err(|_| "本地助手下载地址无效".to_owned())?;
    let origin = Url::parse(server_origin).map_err(|_| "DClaw 服务地址无效".to_owned())?;
    let local_http =
        url.scheme() == "http" && matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "::1"));
    if (url.scheme() != "https" && !local_http)
        || url.scheme() != origin.scheme()
        || url.host_str() != origin.host_str()
        || url.port_or_known_default() != origin.port_or_known_default()
        || !url.path().ends_with(DOWNLOAD_PATH_SUFFIX)
        || url.username() != ""
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err("本地助手下载地址不受信任".to_owned());
    }
    Ok(url)
}

fn switch_current_pointer(app: &AppHandle, metadata: &InstalledHelper) -> Result<(), String> {
    let root = local_helper_directory(app)?;
    fs::create_dir_all(&root).map_err(|error| format!("无法创建本地助手目录: {error}"))?;
    let current = current_pointer_path(app)?;
    let previous = previous_pointer_path(app)?;
    let next = root.join("current.next.json");
    fs::write(
        &next,
        serde_json::to_vec_pretty(metadata)
            .map_err(|error| format!("无法生成本地助手版本信息: {error}"))?,
    )
    .map_err(|error| format!("无法写入本地助手版本信息: {error}"))?;
    let _ = fs::remove_file(&previous);
    if current.is_file() {
        fs::rename(&current, &previous)
            .map_err(|error| format!("无法保存上一版本地助手: {error}"))?;
    }
    if let Err(error) = fs::rename(&next, &current) {
        if previous.is_file() {
            let _ = fs::rename(&previous, &current);
        }
        return Err(format!("无法启用新版本地助手: {error}"));
    }
    Ok(())
}

fn restore_previous_pointer(app: &AppHandle) -> Result<bool, String> {
    let current = current_pointer_path(app)?;
    let previous = previous_pointer_path(app)?;
    if !previous.is_file() {
        return Ok(false);
    }
    let failed = local_helper_directory(app)?.join("failed.json");
    let _ = fs::remove_file(&failed);
    if current.is_file() {
        fs::rename(&current, &failed)
            .map_err(|error| format!("无法隔离失败的本地助手版本: {error}"))?;
    }
    fs::rename(&previous, &current).map_err(|error| format!("无法回退本地助手版本: {error}"))?;
    Ok(true)
}

#[tauri::command]
pub(crate) async fn install_local_helper(
    app: AppHandle,
    state: State<'_, LocalHelperProcessState>,
    request: LocalHelperInstallRequest,
) -> Result<LocalHelperStatus, String> {
    if !cfg!(target_os = "windows") {
        return local_helper_status_value(&app);
    }
    if !valid_version(&request.version)
        || request.protocol_version.is_empty()
        || request.protocol_version.len() > 32
        || !valid_sha256(&request.sha256)
        || request.size_bytes == 0
        || request.size_bytes > MAX_HELPER_BYTES
    {
        return Err("本地助手版本清单无效".to_owned());
    }
    if let Some((installed, _)) = installed_helper(&app)? {
        if installed.version == request.version
            && installed.sha256.eq_ignore_ascii_case(&request.sha256)
            && installed.size_bytes == request.size_bytes
        {
            return local_helper_status_value(&app);
        }
    }
    let url = validate_download_url(&request.download_url, &request.server_origin)?;
    let mut download = reqwest::Client::new().get(url);
    if let Some(authorization) = request.authorization.as_deref() {
        if !authorization.starts_with("Bearer ") || authorization.contains(['\r', '\n']) {
            return Err("本地助手下载凭证无效".to_owned());
        }
        download = download.header(AUTHORIZATION, authorization);
    }
    let response = download
        .send()
        .await
        .map_err(|error| format!("下载本地助手失败: {error}"))?
        .error_for_status()
        .map_err(|error| format!("下载本地助手失败: {error}"))?;
    if response.content_length() != Some(request.size_bytes) {
        return Err("本地助手下载大小与版本清单不一致".to_owned());
    }
    let bytes = response
        .bytes()
        .await
        .map_err(|error| format!("读取本地助手下载内容失败: {error}"))?;
    if bytes.len() as u64 != request.size_bytes {
        return Err("本地助手下载大小与版本清单不一致".to_owned());
    }
    let digest = format!("{:x}", Sha256::digest(&bytes));
    if !digest.eq_ignore_ascii_case(&request.sha256) {
        return Err("本地助手下载校验失败".to_owned());
    }

    let root = local_helper_directory(&app)?;
    let release_name = format!("{}-{}", request.version, &digest[..12]);
    let release_dir = root.join("versions").join(&release_name);
    fs::create_dir_all(&release_dir)
        .map_err(|error| format!("无法创建本地助手版本目录: {error}"))?;
    let executable = release_dir.join("DClaw.LocalHelper.exe");
    let partial = release_dir.join("DClaw.LocalHelper.exe.partial");
    fs::write(&partial, &bytes).map_err(|error| format!("无法写入本地助手: {error}"))?;
    if executable.is_file() {
        fs::remove_file(&executable).map_err(|error| format!("无法替换本地助手: {error}"))?;
    }
    fs::rename(&partial, &executable).map_err(|error| format!("无法启用本地助手文件: {error}"))?;

    stop_local_helper_process(&app, &state)?;
    switch_current_pointer(
        &app,
        &InstalledHelper {
            version: request.version,
            protocol_version: request.protocol_version,
            sha256: digest,
            size_bytes: request.size_bytes,
            executable: Path::new("versions")
                .join(release_name)
                .join("DClaw.LocalHelper.exe")
                .to_string_lossy()
                .into_owned(),
        },
    )?;
    local_helper_status_value(&app)
}

fn launch_local_helper(executable: &Path, config_path: &Path) -> Result<Child, String> {
    let mut command = Command::new(executable);
    command
        .arg(config_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command
        .spawn()
        .map_err(|error| format!("无法启动本地助手: {error}"))
}

#[tauri::command]
pub(crate) fn start_local_helper(
    app: AppHandle,
    state: State<'_, LocalHelperProcessState>,
    request: LocalHelperStartRequest,
) -> Result<LocalHelperStatus, String> {
    if !cfg!(target_os = "windows") {
        return local_helper_status_value(&app);
    }
    let Some((metadata, executable)) = installed_helper(&app)? else {
        return Err("当前超级专家插件未安装本地助手，请重新检测后重试。".to_owned());
    };
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
    });
    fs::write(
        &config_path,
        serde_json::to_vec_pretty(&config)
            .map_err(|error| format!("无法生成本地助手配置: {error}"))?,
    )
    .map_err(|error| format!("无法写入本地助手配置: {error}"))?;

    let mut child = launch_local_helper(&executable, &config_path)?;
    std::thread::sleep(Duration::from_millis(200));
    if child
        .try_wait()
        .map_err(|error| format!("无法检测本地助手进程: {error}"))?
        .is_some()
    {
        if !restore_previous_pointer(&app)? {
            return Err(format!("本地助手 v{} 启动失败", metadata.version));
        }
        let Some((_previous, previous_executable)) = installed_helper(&app)? else {
            return Err("本地助手回退版本不可用".to_owned());
        };
        child = launch_local_helper(&previous_executable, &config_path)?;
    }
    *state
        .child
        .lock()
        .map_err(|_| "本地助手进程状态不可用".to_owned())? = Some(child);
    let mut status = local_helper_status_value(&app)?;
    status.running = true;
    Ok(status)
}

#[cfg(test)]
mod tests {
    use super::{
        config_has_device_token, safe_relative_path, valid_sha256, valid_version,
        validate_download_url,
    };
    use std::fs;
    use std::time::SystemTime;

    #[test]
    fn helper_release_identifiers_are_path_safe() {
        assert!(valid_version("1.3.0-rc.1"));
        assert!(!valid_version("../helper"));
        assert!(valid_sha256(&"a".repeat(64)));
        assert!(!valid_sha256(&"g".repeat(64)));
        assert!(safe_relative_path("versions/1.3.0/DClaw.LocalHelper.exe"));
        assert!(!safe_relative_path("../DClaw.LocalHelper.exe"));
    }

    #[test]
    fn helper_download_must_use_the_authenticated_server_origin() {
        assert!(validate_download_url(
            "https://dclaw.example/api/super-agent-support/local-helper/download?platform=windows-x64",
            "https://dclaw.example",
        )
        .is_ok());
        assert!(validate_download_url(
            "https://evil.example/api/super-agent-support/local-helper/download?platform=windows-x64",
            "https://dclaw.example",
        )
        .is_err());
        assert!(validate_download_url(
            "http://127.0.0.1:8088/api/super-agent-support/local-helper/download?platform=windows-x64",
            "http://127.0.0.1:8088",
        )
        .is_ok());
    }

    #[test]
    fn pairing_requires_a_persisted_device_token() {
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
