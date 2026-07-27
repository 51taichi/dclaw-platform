import { consoleApi } from "../../../api/modules/console";

interface LiveResponseState {
  streamText: string;
  fallbackText: string;
}

const liveResponses = new Map<string, LiveResponseState>();

function getState(sessionId: string): LiveResponseState {
  const existing = liveResponses.get(sessionId);
  if (existing) return existing;
  const created = { streamText: "", fallbackText: "" };
  liveResponses.set(sessionId, created);
  return created;
}

export function resetLiveResponseText(sessionId: string | null | undefined) {
  if (!sessionId) return;
  liveResponses.set(sessionId, { streamText: "", fallbackText: "" });
}

export function appendLiveResponseText(
  sessionId: string | null | undefined,
  chunk: string,
) {
  if (!sessionId || !chunk) return;
  getState(sessionId).streamText += chunk;
}

export function getLiveResponseText(sessionId: string | null | undefined) {
  if (!sessionId) return "";
  const state = liveResponses.get(sessionId);
  if (!state) return "";
  return state.streamText || state.fallbackText;
}

export function clearLiveResponseText(sessionId: string | null | undefined) {
  if (!sessionId) return;
  liveResponses.delete(sessionId);
}

export function clearAllLiveResponseText() {
  liveResponses.clear();
}

export async function hydrateLiveResponseText(sessionId: string) {
  if (!sessionId || getLiveResponseText(sessionId)) {
    return getLiveResponseText(sessionId);
  }

  try {
    const response = await consoleApi.getPushMessages(sessionId);
    const pushedText = (response?.messages || [])
      .map((message) => message.text)
      .filter(Boolean)
      .join("\n\n");

    if (pushedText) {
      getState(sessionId).fallbackText = pushedText;
    }
  } catch {
    /* Push messages are a best-effort bridge for running sessions. */
  }

  return getLiveResponseText(sessionId);
}
