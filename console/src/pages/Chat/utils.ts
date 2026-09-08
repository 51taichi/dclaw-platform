// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
import { chatApi } from "../../api/modules/chat";
import { buildWorkspacePreviewUrl } from "./components/previewUrl";
export type CopyableContent = {
  type?: string;
  text?: string;
  refusal?: string;
};

export type CopyableMessage = {
  role?: string;
  content?: string | CopyableContent[];
};

export type CopyableResponse = {
  output?: CopyableMessage[];
};

export type RuntimeLoadingBridgeApi = {
  getLoading?: () => boolean | string;
  setLoading?: (loading: boolean | string) => void;
};

export type ApprovalSessionLike = {
  session_id?: string;
  root_session_id?: string;
};

function normalizeApprovalSessionIds(
  ids: Array<string | null | undefined>,
): Set<string> {
  return new Set(ids.map((id) => id?.trim()).filter(Boolean) as string[]);
}

export function filterApprovalsForSession<T extends ApprovalSessionLike>(
  approvals: T[],
  sessionIds: Array<string | null | undefined>,
): T[] {
  const candidates = normalizeApprovalSessionIds(sessionIds);
  if (candidates.size === 0) return approvals;

  return approvals.filter(
    (approval) =>
      candidates.has(approval.root_session_id || "") ||
      candidates.has(approval.session_id || ""),
  );
}

// ---------------------------------------------------------------------------
// Text extraction utilities
// ---------------------------------------------------------------------------

/** Extract copyable text from assistant response. */
export function extractCopyableText(response: CopyableResponse): string {
  const collectText = (assistantOnly: boolean) => {
    const chunks = (response.output || []).flatMap((item: CopyableMessage) => {
      if (assistantOnly && item.role !== "assistant") return [];

      if (typeof item.content === "string") {
        return [item.content];
      }

      if (!Array.isArray(item.content)) {
        return [];
      }

      return item.content.flatMap((content: CopyableContent) => {
        if (content.type === "text" && typeof content.text === "string") {
          return [content.text];
        }

        if (content.type === "refusal" && typeof content.refusal === "string") {
          return [content.refusal];
        }

        return [];
      });
    });

    return chunks.filter(Boolean).join("\n\n").trim();
  };

  return collectText(true) || JSON.stringify(response);
}

/** Extract plain text from user message content. */
export function extractUserMessageText(m: any): string {
  if (typeof m.content === "string") return m.content;
  if (!Array.isArray(m.content)) return "";
  return m.content
    .filter((p: any) => p.type === "text")
    .map((p: any) => p.text || "")
    .join("\n");
}

export function extractTextFromMessage(msg: any): string {
  const innerMessage = msg?.cards?.[0]?.data?.input?.[0];
  if (!innerMessage) return "";
  return extractUserMessageText(innerMessage);
}

// ---------------------------------------------------------------------------
// Clipboard utilities
// ---------------------------------------------------------------------------

/** Copy text to clipboard with fallback for non-secure contexts. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);

  let copied = false;
  try {
    textarea.focus();
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }

  if (!copied) {
    throw new Error("Failed to copy text");
  }
}

// ---------------------------------------------------------------------------
// Error response utilities
// ---------------------------------------------------------------------------

/** Build a 400 error response when model is not configured. */
export function buildModelError(): Response {
  return new Response(
    JSON.stringify({
      error: "Model not configured",
      message: "Please configure a model first",
    }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
}

// ---------------------------------------------------------------------------
// URL normalization utilities
// ---------------------------------------------------------------------------

/** Decode each path segment; keeps `/` delimiters (including repeated `/`). */
function decodeUriPathSegments(path: string): string {
  return path
    .split("/")
    .map((segment) => {
      if (!segment) return segment;
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    })
    .join("/");
}

/** Convert file URL to stored path for backend: keep full path after `/files/preview/`. */
export function toStoredName(v: string): string {
  const marker = "/files/preview/";
  const idx = v.indexOf(marker);
  if (idx !== -1) {
    let rest = v.slice(idx + marker.length);
    const q = rest.indexOf("?");
    if (q !== -1) rest = rest.slice(0, q);
    const h = rest.indexOf("#");
    if (h !== -1) rest = rest.slice(0, h);
    if (rest) {
      const decoded = decodeUriPathSegments(rest);
      // Windows absolute path: C:\... or C:/...
      const isWindowsAbsolute = /^[a-zA-Z]:[\\/]/.test(decoded);
      if (isWindowsAbsolute) return decoded;
      return decoded.startsWith("/") ? decoded : `/${decoded}`;
    }
  }
  return v;
}

/** Convert content part URLs to stored name format. */
export function normalizeContentUrls(part: any): any {
  const p = { ...part };
  if (p.type === "image" && typeof p.image_url === "string")
    p.image_url = toStoredName(p.image_url);
  if (p.type === "file" && typeof p.file_url === "string")
    p.file_url = toStoredName(p.file_url);
  if (p.type === "audio" && typeof p.data === "string")
    p.data = toStoredName(p.data);
  if (p.type === "video" && typeof p.video_url === "string")
    p.video_url = toStoredName(p.video_url);
  return p;
}

const IMAGEGEN_MEDIA_PATH_PATTERN =
  /(media\/imagegen\/imagegen_[^/?#]+\.(?:png|jpe?g|webp|gif|bmp|svg))/i;
const WORKSPACE_ABSOLUTE_PATH_PATTERN =
  /\/app\/working\/workspaces\/([^/]+)\/([^?#]+)/i;

function getImagegenMediaPath(url: string): string | null {
  const [pathWithoutQuery] = url.split(/[?#]/);
  const decoded = decodeUriPathSegments(pathWithoutQuery);
  if (
    decoded.includes("/app/working/") ||
    decoded.includes("/files/preview/") ||
    decoded.startsWith("media/imagegen/") ||
    decoded.startsWith("/media/imagegen/")
  ) {
    return decoded.match(IMAGEGEN_MEDIA_PATH_PATTERN)?.[1] || null;
  }
  return null;
}

function getWorkspacePreviewPath(url: string): {
  agentId: string;
  path: string;
} | null {
  const [pathWithoutQuery] = url.split(/[?#]/);
  const decoded = decodeUriPathSegments(pathWithoutQuery);
  const match = decoded.match(WORKSPACE_ABSOLUTE_PATH_PATTERN);
  if (!match) return null;

  const [, pathAgentId, rawPath] = match;
  const parts = rawPath.split("/").filter(Boolean);
  if (parts[0] === "sessions_data" && parts.length > 2) {
    return {
      agentId: pathAgentId,
      path: parts.slice(2).join("/"),
    };
  }
  return {
    agentId: pathAgentId,
    path: parts.join("/"),
  };
}

/** Turn a backend content URL (path or full URL) into a full URL for display. */
export function toDisplayUrl(
  url: string | undefined,
  workspaceId?: string,
  agentId?: string,
): string {
  if (!url) return "";

  const workspacePreviewPath = getWorkspacePreviewPath(url);
  if (workspaceId && workspacePreviewPath) {
    return buildWorkspacePreviewUrl({
      path: workspacePreviewPath.path,
      agentId: agentId || workspacePreviewPath.agentId || "default",
      chatId: workspaceId,
    });
  }

  if (url.startsWith("/api/")) {
    const imagegenMediaPath = getImagegenMediaPath(url);
    if (workspaceId && imagegenMediaPath) {
      return buildWorkspacePreviewUrl({
        path: imagegenMediaPath,
        agentId: agentId || "default",
        chatId: workspaceId,
      });
    }
    return url;
  }

  const rawPath = url.startsWith("file://") ? url.replace("file://", "") : url;
  const imagegenMediaPath = getImagegenMediaPath(rawPath);
  if (workspaceId && imagegenMediaPath) {
    return buildWorkspacePreviewUrl({
      path: imagegenMediaPath,
      agentId: agentId || "default",
      chatId: workspaceId,
    });
  }

  let displayUrl = url;
  if (url.startsWith("file://")) {
    displayUrl = chatApi.filePreviewUrl(rawPath);
  } else if (!url.startsWith("http://") && !url.startsWith("https://") && !url.startsWith("data:")) {
    displayUrl = chatApi.filePreviewUrl(url);
  }

  if (workspaceId && (displayUrl.includes("/api/") || displayUrl.includes("/console/"))) {
    if (!displayUrl.includes("chatId=")) {
      const separator = displayUrl.includes("?") ? "&" : "?";
      displayUrl += `${separator}chatId=${encodeURIComponent(workspaceId)}`;
      if (agentId) {
        displayUrl += `&agent_id=${encodeURIComponent(agentId)}`;
      }
    }
  }
  return displayUrl;
}

/** Recursively rewrite media URLs in backend stream payload so they load correctly in UI. */
export function rewritePayloadMediaUrls(
  payload: any,
  workspaceId?: string,
  agentId?: string,
): any {
  if (!payload || typeof payload !== "object") return payload;

  if (Array.isArray(payload)) {
    for (let i = 0; i < payload.length; i++) {
      rewritePayloadMediaUrls(payload[i], workspaceId, agentId);
    }
    return payload;
  }

  if (
    ["image", "video", "audio"].includes(payload.type) &&
    payload.source &&
    typeof payload.source === "object" &&
    payload.source.type === "url" &&
    typeof payload.source.url === "string"
  ) {
    payload.source.url = toDisplayUrl(payload.source.url, workspaceId, agentId);
  }

  // Rewrite standard content items like {"type": "image", "image_url": "..."}
  if (payload.type === "image" && typeof payload.image_url === "string") {
    payload.image_url = toDisplayUrl(payload.image_url, workspaceId, agentId);
  }
  if (payload.type === "audio" && typeof payload.data === "string") {
    payload.data = toDisplayUrl(payload.data, workspaceId, agentId);
  }
  if (payload.type === "video" && typeof payload.video_url === "string") {
    payload.video_url = toDisplayUrl(payload.video_url, workspaceId, agentId);
  }
  if (payload.type === "file" && (typeof payload.file_url === "string" || typeof payload.file_id === "string")) {
    payload.file_url = toDisplayUrl(
      payload.file_url || payload.file_id,
      workspaceId,
      agentId,
    );
  }

  for (const key of Object.keys(payload)) {
    const val = payload[key];
    if (typeof val === "object" && val !== null) {
      rewritePayloadMediaUrls(val, workspaceId, agentId);
    } else if (typeof val === "string" && (val.startsWith("{") || val.startsWith("["))) {
      try {
        const parsed = JSON.parse(val);
        const rewritten = rewritePayloadMediaUrls(parsed, workspaceId, agentId);
        // Only stringify back if it actually changed, to avoid unnecessary string manipulations
        // However, since it's hard to deeply compare efficiently, we can just stringify it.
        // But doing it blindly on every string might be slow or corrupt non-json strings that just happen to start with { or [.
        // But in our backend payloads, tool responses/arguments are the main JSON strings.
        payload[key] = JSON.stringify(rewritten);
      } catch (e) {
        // Not valid JSON, ignore
      }
    }
  }
  
  return payload;
}

// ---------------------------------------------------------------------------
// DOM utilities
// ---------------------------------------------------------------------------

/** Set textarea value and trigger input event for React state sync.
 * Uses native value setter to bypass React's internal value tracker.
 */
export function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  if (nativeValueSetter) {
    nativeValueSetter.call(textarea, value);
  } else {
    textarea.value = value;
  }
  textarea.selectionStart = textarea.selectionEnd = value.length;
  const event = new Event("input", { bubbles: true });
  textarea.dispatchEvent(event);
}
