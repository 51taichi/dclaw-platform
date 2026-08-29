declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

declare global {
  interface Window {
    __DCLAW_DESKTOP_API_BASE_URL__?: string;
  }
}

const AUTH_TOKEN_KEY = "qwenpaw_auth_token";

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
const USER_PREFIXES = [
  "/agents",
  "/console",
  "/runner",
  "/messages",
  "/workspace",
  "/files",
  "/settings",
  "/skills",
  "/skills_stream",
  "/tools",
  "/plan",
  "/mcp_oauth",
  "/chats",
  "/aigc-studio",
  "/runtime",
  "/expert-teams",
  "/expert-team-runs",
  "/billing",
];

const ADMIN_PREFIXES = [
  "/config",
  "/cron",
  "/local-models",
  "/mcp",
  "/providers",
  "/envs",
  "/token-usage",
  "/agent-stats",
  "/plugins",
  "/backups",
  "/capabilities/admin",
  "/open-api",
];

function getApiBaseUrl(): string {
  if (
    typeof window !== "undefined" &&
    typeof window.__DCLAW_DESKTOP_API_BASE_URL__ === "string" &&
    window.__DCLAW_DESKTOP_API_BASE_URL__
  ) {
    return window.__DCLAW_DESKTOP_API_BASE_URL__.replace(/\/$/, "");
  }
  return VITE_API_BASE_URL || "";
}

export function getApiUrl(path: string): string {
  const base = getApiBaseUrl();
  const apiPrefix = "/api";
  let normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // If path doesn't already have /user or /admin prefix, check if it should
  if (
    !normalizedPath.startsWith("/user/") &&
    !normalizedPath.startsWith("/admin/")
  ) {
    if (ADMIN_PREFIXES.some((p) => normalizedPath.startsWith(p))) {
      normalizedPath = `/admin${normalizedPath}`;
    } else if (USER_PREFIXES.some((p) => normalizedPath.startsWith(p))) {
      normalizedPath = `/user${normalizedPath}`;
    } else if (normalizedPath.startsWith("/capabilities/user")) {
      normalizedPath = `/user${normalizedPath}`;
    }
  }

  return `${base}${apiPrefix}${normalizedPath}`;
}

/**
 * Get the API token - checks localStorage first (auth login),
 * then falls back to the build-time TOKEN constant.
 * @returns API token string or empty string
 */
export function getApiToken(): string {
  const stored = localStorage.getItem(AUTH_TOKEN_KEY);
  if (stored) return stored;
  return typeof TOKEN !== "undefined" ? TOKEN : "";
}

/**
 * Store the auth token in localStorage after login.
 */
export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

/**
 * Remove the auth token from localStorage (logout / 401).
 */
export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}
