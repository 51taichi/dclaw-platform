const STORAGE_KEY = "qwenpaw-expert-team-selection-by-chat";

function isPersistableChatId(chatId: string | null | undefined): chatId is string {
  return !!chatId && chatId !== "draft-session";
}

function readMap(): Record<string, string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, string>)
      : {};
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return {};
  }
}

function writeMap(value: Record<string, string>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* ignore storage quota / private mode errors */
  }
}

export function saveExpertTeamSelectionForChat(
  chatId: string | null | undefined,
  teamId: string | null | undefined,
): void {
  if (!isPersistableChatId(chatId) || !teamId) return;
  writeMap({ ...readMap(), [chatId]: teamId });
}

export function loadExpertTeamSelectionForChat(
  chatId: string | null | undefined,
): string | undefined {
  if (!isPersistableChatId(chatId)) return undefined;
  const teamId = readMap()[chatId];
  return typeof teamId === "string" && teamId ? teamId : undefined;
}

export function clearExpertTeamSelectionForChat(
  chatId: string | null | undefined,
): void {
  if (!isPersistableChatId(chatId)) return;
  const map = readMap();
  if (!(chatId in map)) return;
  const { [chatId]: _removed, ...remaining } = map;
  writeMap(remaining);
}
