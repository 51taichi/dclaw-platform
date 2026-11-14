import { invoke } from "@tauri-apps/api/core";
import { buildAuthHeaders } from "@/api/authHeaders";
import { getApiBaseUrl, getApiUrl } from "@/api/config";
import { getDesktopRuntime } from "./runtime";

export const LOCAL_HELPER_ERROR_EVENT = "dclaw:local-helper-error";

export interface LocalHelperStatus {
  supported: boolean;
  installed: boolean;
  running: boolean;
  connected: boolean;
  paired: boolean;
  deviceId: string | null;
  runnerVersion: string;
}

interface DeviceBootstrapResponse {
  paired: boolean;
  device_id: string | null;
  pairing_code: string | null;
  expires_in: number;
  websocket_path: string;
}

interface LocalHelperManifest {
  platform: string;
  version: string;
  protocol_version: string;
  executable: string;
  size_bytes: number;
  sha256: string;
  download_path: string;
}

export interface LocalHelperEnsureResult {
  available: boolean;
  status: LocalHelperStatus | null;
}

export interface LocalEnvironmentStatus {
  state:
    | "ready"
    | "device_not_ready"
    | "runner_update_required"
    | "protocol_incompatible";
  reason: string;
  protocol_version: string;
  compatible: boolean;
  minimum_runner_version: string;
  user_action: string;
}

export async function getLocalEnvironmentStatus(): Promise<LocalEnvironmentStatus> {
  const response = await fetch(
    getApiUrl("/super-agent-support/environment-status"),
    { headers: buildAuthHeaders() },
  );
  if (!response.ok) {
    throw new Error(`本地助手服务检测失败 (${response.status})`);
  }
  return response.json() as Promise<LocalEnvironmentStatus>;
}

export async function waitForLocalHelperConnection(
  maxAttempts = 40,
  intervalMs = 500,
): Promise<LocalHelperStatus | null> {
  let status: LocalHelperStatus | null = null;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    status = await getLocalHelperStatus();
    if (!status || status.connected || !status.running) return status;
    if (attempt < maxAttempts - 1) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
  return status;
}

export function toWebSocketUrl(path: string): string {
  const configuredBase = getApiBaseUrl();
  const base = configuredBase || window.location.origin;
  const url = new URL(path, `${base.replace(/\/$/, "")}/`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export async function getLocalHelperStatus(): Promise<LocalHelperStatus | null> {
  const runtime = await getDesktopRuntime();
  if (!runtime || runtime.platform !== "windows") return null;
  return invoke<LocalHelperStatus>("get_local_helper_status");
}

export async function ensureLocalHelper(): Promise<LocalHelperEnsureResult> {
  const status = await getLocalHelperStatus();
  if (!status) return { available: false, status: null };
  const runtime = await getDesktopRuntime();
  if (!runtime || runtime.platform !== "windows") {
    return { available: false, status: null };
  }
  const platform = runtime.arch === "x86_64" ? "windows-x64" : "";
  if (!platform) return { available: false, status };
  const authHeaders = buildAuthHeaders();
  const manifestResponse = await fetch(
    getApiUrl(
      `/super-agent-support/local-helper/manifest?platform=${platform}`,
    ),
    { headers: authHeaders },
  );
  if (manifestResponse.status === 404) {
    return { available: false, status };
  }
  if (!manifestResponse.ok) {
    const body = (await manifestResponse.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(
      body.detail || `本地助手版本检测失败 (${manifestResponse.status})`,
    );
  }
  const manifest = (await manifestResponse.json()) as LocalHelperManifest;
  if (
    manifest.platform !== platform ||
    manifest.executable !== "DClaw.LocalHelper.exe" ||
    !manifest.version ||
    !manifest.protocol_version ||
    !Number.isSafeInteger(manifest.size_bytes) ||
    manifest.size_bytes <= 0 ||
    !/^[0-9a-f]{64}$/.test(manifest.sha256) ||
    !manifest.download_path
  ) {
    throw new Error("本地助手版本清单无效");
  }
  const serverOrigin = getApiBaseUrl() || window.location.origin;
  const downloadUrl = new URL(
    manifest.download_path,
    `${serverOrigin.replace(/\/$/, "")}/`,
  ).toString();
  const installed = await invoke<LocalHelperStatus>("install_local_helper", {
    request: {
      downloadUrl,
      serverOrigin,
      authorization: authHeaders.Authorization || null,
      version: manifest.version,
      protocolVersion: manifest.protocol_version,
      sha256: manifest.sha256,
      sizeBytes: manifest.size_bytes,
    },
  });

  const response = await fetch(
    getApiUrl("/super-agent-support/device-bootstrap"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      },
      body: JSON.stringify({
        device_id: installed.paired ? installed.deviceId : null,
      }),
    },
  );
  if (response.status === 404) {
    return { available: false, status: installed };
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(body.detail || `本地助手配对失败 (${response.status})`);
  }

  const bootstrap = (await response.json()) as DeviceBootstrapResponse;
  const started = await invoke<LocalHelperStatus>("start_local_helper", {
    request: {
      serverWebsocketUri: toWebSocketUrl(bootstrap.websocket_path),
      pairingCode: bootstrap.paired ? null : bootstrap.pairing_code,
    },
  });
  return { available: true, status: started };
}

export async function stopLocalHelper(): Promise<void> {
  const runtime = await getDesktopRuntime();
  if (!runtime || runtime.platform !== "windows") return;
  await invoke("stop_local_helper");
}

export function reportLocalHelperError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  window.dispatchEvent(
    new CustomEvent(LOCAL_HELPER_ERROR_EVENT, { detail: { message } }),
  );
  console.error("DClaw local helper:", message);
}
