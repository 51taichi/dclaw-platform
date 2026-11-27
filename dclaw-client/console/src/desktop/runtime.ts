import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { isDesktopApp } from "@/utils/env";

export interface DesktopRuntimeInfo {
  brandId: string;
  version: string;
  platform: string;
  arch: string;
}

declare const DCLAW_DESKTOP_BRAND_ID: string;

let runtimePromise: Promise<DesktopRuntimeInfo | null> | undefined;

export function getDesktopRuntime(): Promise<DesktopRuntimeInfo | null> {
  if (!runtimePromise) {
    runtimePromise = loadDesktopRuntime();
  }
  return runtimePromise;
}

async function loadDesktopRuntime(): Promise<DesktopRuntimeInfo | null> {
  if (!isDesktopApp() || !("__TAURI_INTERNALS__" in window)) return null;
  const status = await invoke<{ platform: string; arch: string }>(
    "get_app_status",
  );
  return {
    brandId: DCLAW_DESKTOP_BRAND_ID,
    version: await getVersion(),
    platform: status.platform,
    arch: status.arch,
  };
}
