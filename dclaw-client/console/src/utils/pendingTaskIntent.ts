export interface PendingTaskIntent {
  prompt: string;
  agentId: string;
  expertTeam?: unknown;
}

const STORAGE_PREFIX = "qwenpaw_pending_task_intent_";

function storageKey(chatId: string): string {
  return `${STORAGE_PREFIX}${chatId}`;
}

function isPendingTaskIntent(value: unknown): value is PendingTaskIntent {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.prompt === "string" &&
    record.prompt.trim().length > 0 &&
    typeof record.agentId === "string" &&
    record.agentId.trim().length > 0
  );
}

export function savePendingTaskIntent(
  chatId: string,
  intent: PendingTaskIntent,
): void {
  if (!chatId || !isPendingTaskIntent(intent)) return;
  try {
    sessionStorage.setItem(storageKey(chatId), JSON.stringify(intent));
  } catch {
    /* ignore storage failures */
  }
}

export function loadPendingTaskIntent(
  chatId: string,
): PendingTaskIntent | null {
  if (!chatId) return null;
  try {
    const raw = sessionStorage.getItem(storageKey(chatId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return isPendingTaskIntent(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function clearPendingTaskIntent(chatId: string): void {
  if (!chatId) return;
  try {
    sessionStorage.removeItem(storageKey(chatId));
  } catch {
    /* ignore storage failures */
  }
}
