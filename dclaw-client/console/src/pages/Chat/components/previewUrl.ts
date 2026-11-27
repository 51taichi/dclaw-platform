import { getApiToken, getApiUrl } from "../../../api/config";

const PREVIEW_CONTEXT_PREFIX = "__qwenpaw_preview__";

function encodePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
}

export function buildWorkspacePreviewUrl({
  path,
  agentId,
  chatId,
  version,
}: {
  path: string;
  agentId?: string | null;
  chatId?: string | null;
  version?: number;
}): string {
  const cleanPath = encodePath(path || "index.html") || "index.html";
  const params = new URLSearchParams();
  if (version !== undefined) {
    params.append("v", version.toString());
  }
  const token = getApiToken();
  if (token) {
    params.append("token", token);
  }
  const queryStr = params.toString();
  const suffix = queryStr ? `?${queryStr}` : "";

  if (agentId && chatId) {
    return getApiUrl(
      `/workspace/preview/${PREVIEW_CONTEXT_PREFIX}/${encodeURIComponent(
        agentId,
      )}/${encodeURIComponent(chatId)}/${cleanPath}${suffix}`,
    );
  }

  if (agentId) {
    params.append("agent_id", agentId);
  }
  if (chatId) {
    params.append("chatId", chatId);
  }

  const fallbackQuery = params.toString();
  return getApiUrl(
    `/workspace/preview/${cleanPath}${fallbackQuery ? `?${fallbackQuery}` : ""}`,
  );
}
