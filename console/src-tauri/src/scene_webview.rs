use serde::Deserialize;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tauri::{
    webview::{NewWindowResponse, WebviewBuilder},
    AppHandle, LogicalPosition, LogicalSize, Manager, Rect, WebviewUrl, WebviewWindowBuilder,
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

fn scene_webview_rect(
    bounds: &SceneWebviewBounds,
    origin: LogicalPosition<f64>,
) -> Result<Rect, String> {
    bounds.validate()?;
    Ok(Rect {
        position: LogicalPosition::new(origin.x + bounds.x, origin.y + bounds.y).into(),
        size: LogicalSize::new(bounds.width, bounds.height).into(),
    })
}

fn main_window_content_origin(_app: &AppHandle) -> Result<LogicalPosition<f64>, String> {
    #[cfg(target_os = "macos")]
    {
        let window = _app
            .get_window("main")
            .ok_or_else(|| "DClaw 主窗口不可用".to_owned())?;
        let scale_factor = window
            .scale_factor()
            .map_err(|error| format!("无法读取主窗口缩放比例: {error}"))?;
        let inner_position = window
            .inner_position()
            .map_err(|error| format!("无法读取主窗口内容区位置: {error}"))?
            .to_logical::<f64>(scale_factor);
        let outer_position = window
            .outer_position()
            .map_err(|error| format!("无法读取主窗口外框位置: {error}"))?
            .to_logical::<f64>(scale_factor);

        Ok(LogicalPosition::new(
            (inner_position.x - outer_position.x).max(0.0),
            (inner_position.y - outer_position.y).max(0.0),
        ))
    }

    #[cfg(not(target_os = "macos"))]
    {
        Ok(LogicalPosition::new(0.0, 0.0))
    }
}

fn set_scene_webview_bounds(
    app: &AppHandle,
    webview: &tauri::Webview,
    bounds: &SceneWebviewBounds,
) -> Result<(), String> {
    webview
        .set_bounds(scene_webview_rect(
            bounds,
            main_window_content_origin(app)?,
        )?)
        .map_err(|error| format!("无法调整外链场景显示区域: {error}"))
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
        set_scene_webview_bounds(&app, &webview, &bounds)?;
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
    let origin = main_window_content_origin(&app)?;
    let webview = main_window
        .add_child(
            webview_builder,
            LogicalPosition::new(origin.x + bounds.x, origin.y + bounds.y),
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
        set_scene_webview_bounds(&app, &webview, &bounds)?;
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
        is_external_web_url, scene_webview_label, scene_webview_rect, scene_webview_url,
        SceneWebviewBounds, SCENE_WEBVIEW_PREFIX,
    };
    use tauri::{LogicalPosition, LogicalSize, Position, Size};

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

    #[test]
    fn scene_bounds_include_the_window_content_origin() {
        let bounds = SceneWebviewBounds {
            x: 8.0,
            y: 56.0,
            width: 1200.0,
            height: 700.0,
        };

        let rect = scene_webview_rect(&bounds, LogicalPosition::new(0.0_f64, 28.0_f64)).unwrap();

        assert_eq!(
            rect.position,
            Position::Logical(LogicalPosition::new(8.0, 84.0))
        );
        assert_eq!(rect.size, Size::Logical(LogicalSize::new(1200.0, 700.0)));
    }
}
