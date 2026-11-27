import { getApiBaseUrl } from "@/api/config";
import { getDesktopRuntime } from "./runtime";

export const DESKTOP_UPDATE_REQUIRED_EVENT = "dclaw:desktop-update-required";

function isInternalApiRequest(input: RequestInfo | URL): boolean {
  const raw = input instanceof Request ? input.url : String(input);
  const base = getApiBaseUrl();
  if (raw.startsWith("/api/")) return true;
  if (!base) return raw.startsWith(`${window.location.origin}/api/`);
  return raw.startsWith(`${base}/api/`);
}

export async function installDesktopHttpGate(): Promise<void> {
  const runtime = await getDesktopRuntime();
  if (!runtime) return;

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!isInternalApiRequest(input)) return originalFetch(input, init);

    const sourceHeaders =
      init?.headers ?? (input instanceof Request ? input.headers : undefined);
    const headers = new Headers(sourceHeaders);
    headers.set("X-DClaw-Desktop-Brand", runtime.brandId);
    headers.set("X-DClaw-Desktop-Version", runtime.version);
    headers.set("X-DClaw-Desktop-Platform", runtime.platform);
    headers.set("X-DClaw-Desktop-Arch", runtime.arch);

    const response = await originalFetch(input, { ...init, headers });
    if (response.status === 426) {
      window.dispatchEvent(new CustomEvent(DESKTOP_UPDATE_REQUIRED_EVENT));
    }
    return response;
  };
}
