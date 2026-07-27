/**
 * Detect whether the current host environment is a desktop client application
 * (either Tauri or Pywebview container).
 */
export function isDesktopApp(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  // 1. Check for Tauri v2/v1 global environment variables
  const hasTauri = "__TAURI_INTERNALS__" in window;

  // 2. Check for Pywebview global interface
  const hasPywebview = "pywebview" in window;

  return hasTauri || hasPywebview;
}

/**
 * Get simple host environment identifier.
 */
export function getHostEnvironment(): "desktop" | "web" {
  return isDesktopApp() ? "desktop" : "web";
}
