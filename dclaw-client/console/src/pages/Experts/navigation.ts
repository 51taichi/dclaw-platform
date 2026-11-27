interface ResolveExpertSummonTargetInput {
  from?: string;
  isTeam: boolean;
  startNewChat?: boolean;
  lastChatId?: string;
}

export function resolveExpertSummonTarget({
  from = "/workbench",
  isTeam,
  startNewChat = false,
  lastChatId,
}: ResolveExpertSummonTargetInput): string {
  const normalizedFrom = from.startsWith("/chat/")
    ? from.replace(/^\/chat/, "/task")
    : from;
  const isFromTask = /^\/task\/[^/]+$/.test(normalizedFrom);
  const prefix = "/task";

  if (isTeam && isFromTask) {
    return prefix;
  }

  if (isFromTask && startNewChat) {
    return prefix;
  }

  if (!isTeam && isFromTask && lastChatId) {
    return `${prefix}/${lastChatId}`;
  }

  return normalizedFrom;
}
