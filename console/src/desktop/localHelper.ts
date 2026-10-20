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

export interface LocalHelperEnsureResult {
  available: boolean;
  status: LocalHelperStatus | null;
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
  if (!status.installed) {
    throw new Error("当前 DClaw 安装包未包含通用本地助手，请升级客户端。");
  }

  const response = await fetch(
    getApiUrl("/super-agent-support/device-bootstrap"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      },
      body: JSON.stringify({
        device_id: status.paired ? status.deviceId : null,
      }),
    },
  );
  if (response.status === 404) {
    return { available: false, status };
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
