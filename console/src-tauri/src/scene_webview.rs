use serde::Deserialize;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tauri::{
    webview::{NewWindowResponse, WebviewBuilder},
    AppHandle, LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_shell::ShellExt;

const SCENE_WEBVIEW_PREFIX: &str = "scene-";
static POPUP_WINDOW_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SceneWebviewBounds {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

impl SceneWebviewBounds {
    fn validate(&self) -> Result<(), String> {
        let values = [self.x, self.y, self.width, self.height];
        if values.iter().any(|value| !value.is_finite())
            || self.x < 0.0
            || self.y < 0.0
            || self.width < 1.0
            || self.height < 1.0
        {
            return Err("外链场景显示区域无效".to_owned());
        }
        Ok(())
    }
}

fn is_external_web_url(url: &tauri::Url) -> bool {
    matches!(url.scheme(), "http" | "https")
}

fn scene_webview_url(value: &str) -> Result<tauri::Url, String> {
    let url = value
        .parse::<tauri::Url>()
        .map_err(|error| format!("外链场景地址无效: {error}"))?;
    if url.scheme() != "https" {
        return Err("外链场景仅支持 HTTPS 地址".to_owned());
    }
    Ok(url)
}

fn scene_webview_label(scene_key: &str, url: &tauri::Url) -> Result<String, String> {
    if scene_key.is_empty() || scene_key.len() > 256 {
        return Err("外链场景标识无效".to_owned());
    }
    let mut hasher = DefaultHasher::new();
    scene_key.hash(&mut hasher);
    url.as_str().hash(&mut hasher);
    Ok(format!("{SCENE_WEBVIEW_PREFIX}{:016x}", hasher.finish()))
}

fn hide_other_scene_webviews(app: &AppHandle, active_label: Option<&str>) {
    for (label, webview) in app.webviews() {
        if label.starts_with(SCENE_WEBVIEW_PREFIX) && Some(label.as_str()) != active_label {
            let _ = webview.hide();
        }
    }
}

fn set_scene_webview_bounds(
    webview: &tauri::Webview,
    bounds: &SceneWebviewBounds,
) -> Result<(), String> {
    bounds.validate()?;
    webview
        .set_position(LogicalPosition::new(bounds.x, bounds.y))
        .map_err(|error| format!("无法定位外链场景: {error}"))?;
    webview
        .set_size(LogicalSize::new(bounds.width, bounds.height))
        .map_err(|error| format!("无法调整外链场景大小: {error}"))
}

fn open_scene_popup(
    app: &AppHandle,
    url: tauri::Url,
    features: tauri::webview::NewWindowFeatures,
) -> NewWindowResponse<tauri::Wry> {
    if !is_external_web_url(&url) {
        return NewWindowResponse::Deny;
    }

    #[allow(deprecated)]
    if app.shell().open(url.as_str(), None).is_err() {
        return NewWindowResponse::Deny;
    }

    // Keep window.open() successful after handing the real URL to the system browser.
    let popup_id = POPUP_WINDOW_ID.fetch_add(1, Ordering::Relaxed);
    let label = format!("scene-popup-{popup_id}");
    let builder = WebviewWindowBuilder::new(
        app,
        label,
        WebviewUrl::External("about:blank".parse().expect("valid about URL")),
    )
    .visible(false)
    .focused(false)
    .skip_taskbar(true)
    .window_features(features);

    match builder.build() {
        Ok(window) => {
            let disposable_window = window.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(2));
                let _ = disposable_window.close();
            });
            NewWindowResponse::Create { window }
        }
        Err(_) => NewWindowResponse::Deny,
    }
}

#[tauri::command]
pub(crate) async fn show_scene_webview(
    app: AppHandle,
    scene_key: String,
    url: String,
    bounds: SceneWebviewBounds,
) -> Result<(), String> {
    bounds.validate()?;
    let url = scene_webview_url(&url)?;
    let label = scene_webview_label(&scene_key, &url)?;
    hide_other_scene_webviews(&app, Some(&label));

    if let Some(webview) = app.get_webview(&label) {
        set_scene_webview_bounds(&webview, &bounds)?;
        webview
            .show()
            .map_err(|error| format!("无法显示外链场景: {error}"))?;
        webview
            .set_focus()
            .map_err(|error| format!("无法聚焦外链场景: {error}"))?;
        return Ok(());
    }

    let main_window = app
        .get_window("main")
        .ok_or_else(|| "DClaw 主窗口不可用".to_owned())?;
    let popup_app = app.clone();
    let webview_builder = WebviewBuilder::new(label, WebviewUrl::External(url))
        .on_new_window(move |url, features| open_scene_popup(&popup_app, url, features));
    let webview = main_window
        .add_child(
            webview_builder,
            LogicalPosition::new(bounds.x, bounds.y),
            LogicalSize::new(bounds.width, bounds.height),
        )
        .map_err(|error| format!("无法创建外链场景: {error}"))?;
    webview
        .set_focus()
        .map_err(|error| format!("无法聚焦外链场景: {error}"))
}

#[tauri::command]
pub(crate) async fn resize_scene_webview(
    app: AppHandle,
    scene_key: String,
    url: String,
    bounds: SceneWebviewBounds,
) -> Result<(), String> {
    let url = scene_webview_url(&url)?;
    let label = scene_webview_label(&scene_key, &url)?;
    if let Some(webview) = app.get_webview(&label) {
        set_scene_webview_bounds(&webview, &bounds)?;
    }
    Ok(())
}

#[tauri::command]
pub(crate) fn hide_scene_webviews(app: AppHandle) {
    hide_other_scene_webviews(&app, None);
}

#[cfg(test)]
mod tests {
    use super::{
        is_external_web_url, scene_webview_label, scene_webview_url, SCENE_WEBVIEW_PREFIX,
    };

    #[test]
    fn only_http_links_can_leave_the_embedded_scene() {
        assert!(is_external_web_url(
            &"https://example.com/help".parse().unwrap()
        ));
        assert!(is_external_web_url(
            &"http://example.com/help".parse().unwrap()
        ));
        assert!(!is_external_web_url(
            &"javascript:alert(1)".parse().unwrap()
        ));
        assert!(!is_external_web_url(&"file:///tmp/help".parse().unwrap()));
    }

    #[test]
    fn scene_webviews_only_accept_https_and_use_opaque_labels() {
        let url = scene_webview_url("https://service.example.com/console").unwrap();
        let label = scene_webview_label("customer/service", &url).unwrap();

        assert!(label.starts_with(SCENE_WEBVIEW_PREFIX));
        assert!(!label.contains("customer/service"));
        assert!(scene_webview_url("http://service.example.com").is_err());
        assert!(scene_webview_url("javascript:alert(1)").is_err());
    }
}
