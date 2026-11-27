import type {
  MobileArtifactKind,
  MobileArtifactSummary,
} from "./mobile";

const ARTIFACT_TRIGGER_PATTERN =
  /\[qwenpaw-artifact-card-trigger\]\(http:\/\/qwenpaw\.local\/\?data=([^)]+)\)/g;
const ARTIFACT_HEADING_PATTERN =
  /🎯\s*\*\*本次任务产生的制品和文件变更如下\*\*[：:]?\s*/g;
const MARKDOWN_IMAGE_PATTERN = /!\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)/g;
const MAX_ARTIFACT_RECOVERY_POLLS = 5;

const IMAGE_EXTENSIONS = new Set([
  "apng",
  "avif",
  "bmp",
  "gif",
  "jpeg",
  "jpg",
  "png",
  "webp",
]);
const DOCUMENT_EXTENSIONS = new Set([
  "csv",
  "doc",
  "docx",
  "pdf",
  "ppt",
  "pptx",
  "txt",
  "xls",
  "xlsx",
]);
const ARCHIVE_EXTENSIONS = new Set(["7z", "gz", "rar", "tar", "zip"]);
const CODE_EXTENSIONS = new Set([
  "css",
  "html",
  "js",
  "json",
  "md",
  "py",
  "ts",
  "tsx",
]);

function decodeBase64Utf8(value: string): string {
  const alphabet =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = value.replace(/\s+/g, "").replace(/=+$/, "");
  const bytes: number[] = [];
  let buffer = 0;
  let bitCount = 0;

  for (const char of clean) {
    const index = alphabet.indexOf(char);
    if (index < 0) {
      throw new Error("Invalid base64 payload");
    }
    buffer = (buffer << 6) | index;
    bitCount += 6;
    if (bitCount >= 8) {
      bitCount -= 8;
      bytes.push((buffer >> bitCount) & 0xff);
      buffer &= bitCount ? (1 << bitCount) - 1 : 0;
    }
  }

  const percentEncoded = bytes
    .map((byte) => `%${byte.toString(16).padStart(2, "0")}`)
    .join("");
  try {
    return decodeURIComponent(percentEncoded);
  } catch {
    return bytes.map((byte) => String.fromCharCode(byte)).join("");
  }
}

function decodeArtifactFiles(payload: string): string[] {
  let decodedPayload = payload.trim();
  try {
    decodedPayload = decodeURIComponent(decodedPayload);
  } catch {
    // Keep the original payload when an older message contains a stray '%'.
  }
  const candidates = [decodedPayload];
  try {
    candidates.unshift(decodeBase64Utf8(decodedPayload));
  } catch {
    // Older messages may contain the JSON array directly.
  }

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (Array.isArray(parsed)) {
        return parsed.filter(
          (item): item is string =>
            typeof item === "string" && item.trim().length > 0,
        );
      }
    } catch {
      // Try the next supported trigger payload format.
    }
  }
  return [];
}

export function messageContentText(message: Record<string, unknown>): string {
  const content = message.content;
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      if (item && typeof item === "object" && "text" in item) {
        return String((item as { text?: unknown }).text || "");
      }
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

export function extractArtifactPaths(text: string): string[] {
  const paths: string[] = [];
  const seen = new Set<string>();
  ARTIFACT_TRIGGER_PATTERN.lastIndex = 0;
  for (const match of text.matchAll(ARTIFACT_TRIGGER_PATTERN)) {
    for (const path of decodeArtifactFiles(match[1] || "")) {
      if (seen.has(path)) {
        continue;
      }
      seen.add(path);
      paths.push(path);
    }
  }
  return paths;
}

export function cleanArtifactMessageText(text: string): string {
  return text
    .replace(ARTIFACT_TRIGGER_PATTERN, "")
    .replace(ARTIFACT_HEADING_PATTERN, "")
    .replace(MARKDOWN_IMAGE_PATTERN, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function artifactKind(path: string): MobileArtifactKind {
  const extension = path.includes(".")
    ? String(path.split(".").pop() || "").toLowerCase()
    : "";
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (DOCUMENT_EXTENSIONS.has(extension)) return "document";
  if (ARCHIVE_EXTENSIONS.has(extension)) return "archive";
  if (CODE_EXTENSIONS.has(extension)) return "code";
  return "file";
}

function isHiddenArtifact(path: string): boolean {
  return path.toLowerCase().endsWith(".imagegen.json");
}

export function filterVisibleArtifacts(
  artifacts: MobileArtifactSummary[],
): MobileArtifactSummary[] {
  return artifacts.filter(
    (artifact) => !isHiddenArtifact(artifact.path || artifact.name),
  );
}

function imageReferenceFromValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (!value || typeof value !== "object") {
    return "";
  }
  const record = value as Record<string, unknown>;
  for (const key of ["url", "path", "file_path", "src"]) {
    if (typeof record[key] === "string" && record[key]) {
      return String(record[key]).trim();
    }
  }
  if (typeof record.data === "string" && record.data) {
    const mediaType =
      typeof record.media_type === "string" && record.media_type
        ? record.media_type
        : "image/png";
    return `data:${mediaType};base64,${record.data}`;
  }
  return "";
}

function imageReferenceFromContentPart(item: unknown): string {
  if (!item || typeof item !== "object") {
    return "";
  }
  const record = item as Record<string, unknown>;
  const itemType = String(record.type || "").toLowerCase();
  for (const key of ["image_url", "image", "source"]) {
    const reference = imageReferenceFromValue(record[key]);
    if (reference) {
      return reference;
    }
  }
  if (itemType.includes("image")) {
    for (const key of ["url", "path", "file_path", "src"]) {
      const reference = imageReferenceFromValue(record[key]);
      if (reference) {
        return reference;
      }
    }
  }
  return "";
}

export function normalizeMobileImageReference(reference: string): string {
  const original = reference.trim();
  if (!original || /^(?:https?:|data:image\/|wxfile:|blob:)/i.test(original)) {
    return original;
  }

  let normalized = original;
  if (/^file:\/\//i.test(normalized)) {
    normalized = normalized.replace(/^file:\/\/(?:localhost)?/i, "");
    try {
      normalized = decodeURIComponent(normalized);
    } catch {
      // Keep the undecoded path when the file URL contains a stray '%'.
    }
  }
  normalized = normalized.replace(/\\/g, "/");

  const sessionMarker = "/sessions_data/";
  const sessionIndex = normalized.indexOf(sessionMarker);
  if (sessionIndex >= 0) {
    const afterMarker = normalized.slice(sessionIndex + sessionMarker.length);
    const separatorIndex = afterMarker.indexOf("/");
    if (separatorIndex >= 0) {
      return afterMarker.slice(separatorIndex + 1);
    }
  }

  for (const marker of ["/media/imagegen/", "/artifacts/"]) {
    const markerIndex = normalized.indexOf(marker);
    if (markerIndex >= 0) {
      return normalized.slice(markerIndex + 1);
    }
  }
  return normalized.replace(/^\.\//, "");
}

export function messageImagePaths(
  message: Record<string, unknown>,
): string[] {
  const paths: string[] = [];
  const seen = new Set<string>();
  const append = (path: string) => {
    const normalizedPath = normalizeMobileImageReference(path);
    if (!normalizedPath || seen.has(normalizedPath)) {
      return;
    }
    seen.add(normalizedPath);
    paths.push(normalizedPath);
  };

  const text = messageContentText(message);
  MARKDOWN_IMAGE_PATTERN.lastIndex = 0;
  for (const match of text.matchAll(MARKDOWN_IMAGE_PATTERN)) {
    append(match[1] || "");
  }
  for (const path of extractArtifactPaths(text)) {
    if (!isHiddenArtifact(path) && artifactKind(path) === "image") {
      append(path);
    }
  }

  if (Array.isArray(message.content)) {
    for (const item of message.content) {
      append(imageReferenceFromContentPart(item));
    }
  }
  return paths;
}

export function mergeMessageArtifacts(
  messages: Record<string, unknown>[],
  artifacts: MobileArtifactSummary[],
): MobileArtifactSummary[] {
  const merged = filterVisibleArtifacts(artifacts);
  const seen = new Set(merged.map((artifact) => artifact.path));
  for (const message of messages) {
    for (const path of extractArtifactPaths(messageContentText(message))) {
      if (isHiddenArtifact(path) || seen.has(path)) {
        continue;
      }
      seen.add(path);
      merged.push({
        name: path.split("/").pop() || path,
        path,
        kind: artifactKind(path),
      });
    }
  }
  return merged;
}

export function hasArtifactTrigger(
  messages: Record<string, unknown>[],
): boolean {
  return messages.some((message) => {
    ARTIFACT_TRIGGER_PATTERN.lastIndex = 0;
    return ARTIFACT_TRIGGER_PATTERN.test(messageContentText(message));
  });
}

export function shouldRecoverMissingArtifacts({
  messages,
  artifactCount,
  recoveryPolls,
}: {
  messages: Record<string, unknown>[];
  artifactCount: number;
  recoveryPolls: number;
}): boolean {
  return (
    artifactCount === 0 &&
    recoveryPolls < MAX_ARTIFACT_RECOVERY_POLLS &&
    hasArtifactTrigger(messages)
  );
}
