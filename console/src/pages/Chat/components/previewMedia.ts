export type MediaPreviewKind = "audio" | "video";

const AUDIO_MIME_TYPES: Record<string, string> = {
  mp3: "audio/mpeg",
  mpeg: "audio/mpeg",
  wav: "audio/wav",
  wave: "audio/wav",
  m4a: "audio/mp4",
  aac: "audio/aac",
  ogg: "audio/ogg",
  oga: "audio/ogg",
  opus: "audio/ogg",
  flac: "audio/flac",
  weba: "audio/webm",
  webm: "audio/webm",
  mpga: "audio/mpeg",
};

const VIDEO_MIME_TYPES: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
  ogv: "video/ogg",
  avi: "video/x-msvideo",
  mkv: "video/x-matroska",
  "3gp": "video/3gpp",
  "3g2": "video/3gpp2",
};

function getCleanExtension(path: string): string {
  let decodedPath = path || "";
  try {
    decodedPath = decodeURIComponent(decodedPath);
  } catch {
    decodedPath = path || "";
  }
  const cleanPath = decodedPath.split(/[?#]/)[0].trim().toLowerCase();
  return cleanPath.split(".").pop() || "";
}

export function getMediaPreviewKind(path: string): MediaPreviewKind | null {
  const ext = getCleanExtension(path);
  if (VIDEO_MIME_TYPES[ext]) return "video";
  if (AUDIO_MIME_TYPES[ext]) return "audio";
  return null;
}

export function getMediaMimeType(path: string): string | undefined {
  const ext = getCleanExtension(path);
  return VIDEO_MIME_TYPES[ext] || AUDIO_MIME_TYPES[ext];
}

export function isMediaPreviewFile(path: string): boolean {
  return getMediaPreviewKind(path) !== null;
}
