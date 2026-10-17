import { open } from "@tauri-apps/plugin-shell";

/**
 * Open an external URL, using the pywebview bridge in desktop app or
 * window.open in browser.
 *
 * @param url - The URL to open
 * @param target - Target window name (default: "_blank")
 * @param features - Window features string (default: "noopener,noreferrer")
 */
export function openExternalLink(
  url: string,
  target: string = "_blank",
  features: string = "noopener,noreferrer",
): void {
  if (!url) return;

  const pywebview = window.pywebview;
  if (pywebview?.api?.open_external_link) {
    // Desktop app: use pywebview bridge to open in system browser
    pywebview.api.open_external_link(url);
  } else if ("__TAURI_INTERNALS__" in window) {
    void open(url);
  } else {
    // Web browser: use standard window.open
    window.open(url, target, features);
  }
}
