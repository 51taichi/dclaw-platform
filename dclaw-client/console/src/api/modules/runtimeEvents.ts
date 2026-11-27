import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";

export interface RuntimeEvent {
  id: string;
  type: string;
  scope: string;
  session_id?: string | null;
  chat_id?: string | null;
  job_id?: string | null;
  status?: string | null;
  message?: string;
  payload?: Record<string, unknown>;
  created_at?: number;
}

export interface RuntimeSseFrame {
  event: string;
  data: string;
}

export interface RuntimeEventStreamOptions {
  sessionId: string;
  sinceId?: string | null;
  signal: AbortSignal;
  onOpen?: () => void;
  onEvent: (event: RuntimeEvent) => void;
  onHeartbeat?: () => void;
}

export function buildRuntimeEventsStreamUrl(
  sessionId: string,
  sinceId?: string | null,
): string {
  const params = new URLSearchParams({ session_id: sessionId });
  if (sinceId) {
    params.set("since_id", sinceId);
  }
  return getApiUrl(`/runtime/events/stream?${params.toString()}`);
}

export function takeRuntimeSseFrames(buffer: string): {
  frames: string[];
  rest: string;
} {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n\n");
  const rest = parts.pop() ?? "";
  return {
    frames: parts.filter((part) => part.trim().length > 0),
    rest,
  };
}

export function parseRuntimeSseFrame(frame: string): RuntimeSseFrame | null {
  const dataLines: string[] = [];
  let event = "message";

  for (const rawLine of frame.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    const field = separator >= 0 ? rawLine.slice(0, separator) : rawLine;
    let value = separator >= 0 ? rawLine.slice(separator + 1) : "";
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }

    if (field === "event") {
      event = value;
    } else if (field === "data") {
      dataLines.push(value);
    }
  }

  if (!dataLines.length) {
    return null;
  }
  return {
    event,
    data: dataLines.join("\n"),
  };
}

export async function streamRuntimeEvents({
  sessionId,
  sinceId,
  signal,
  onOpen,
  onEvent,
  onHeartbeat,
}: RuntimeEventStreamOptions): Promise<void> {
  const response = await fetch(
    buildRuntimeEventsStreamUrl(sessionId, sinceId),
    {
      headers: buildAuthHeaders(),
      signal,
    },
  );
  if (!response.ok) {
    throw new Error(`Runtime event stream failed: ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Runtime event stream response has no body");
  }

  onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const extracted = takeRuntimeSseFrames(buffer);
    buffer = extracted.rest;
    for (const frame of extracted.frames) {
      const parsed = parseRuntimeSseFrame(frame);
      if (!parsed) continue;
      if (parsed.event === "heartbeat") {
        onHeartbeat?.();
      } else if (parsed.event === "runtime_event") {
        onEvent(JSON.parse(parsed.data) as RuntimeEvent);
      }
    }
  }
}
