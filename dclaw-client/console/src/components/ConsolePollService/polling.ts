export const VISIBLE_POLL_INTERVAL_MS = 15_000;
export const HIDDEN_POLL_INTERVAL_MS = 60_000;

export function getConsolePollDelay(visibilityState: DocumentVisibilityState) {
  return visibilityState === "visible"
    ? VISIBLE_POLL_INTERVAL_MS
    : HIDDEN_POLL_INTERVAL_MS;
}

