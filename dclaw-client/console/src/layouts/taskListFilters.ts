import type { ChatSpec } from "../api";

export interface TaskListChat extends ChatSpec {
  message_count?: number;
}

export type TaskArchiveView = "active" | "archived";

export function isArchivedTaskChat(chat: TaskListChat): boolean {
  return chat.meta?.archived === true;
}

export function matchesTaskArchiveView(
  chat: TaskListChat,
  archiveView: TaskArchiveView,
): boolean {
  const archived = isArchivedTaskChat(chat);
  return archiveView === "archived" ? archived : !archived;
}

export function buildTaskArchiveMeta(
  currentMeta: Record<string, unknown> | undefined,
  archived: boolean,
  archivedAt?: string,
): Record<string, unknown> {
  return {
    ...(currentMeta ?? {}),
    archived,
    archived_at: archived ? (archivedAt ?? new Date().toISOString()) : null,
  };
}

export function isVisibleTaskChat(chat: TaskListChat): boolean {
  const id = chat.id?.trim();
  if (!id || id === "undefined" || id === "null") return false;
  if (id === "claw-global-session") return false;
  if (chat.channel === "claw") return false;
  if (
    chat.meta &&
    typeof chat.meta === "object" &&
    "mode" in chat.meta &&
    (chat.meta as Record<string, unknown>).mode === "claw"
  ) {
    return false;
  }

  const name = (chat.name || "").trim();
  if (
    name === "New Chat" &&
    chat.status !== "running" &&
    (chat.message_count === 0 || chat.message_count == null)
  ) {
    return false;
  }

  return true;
}
