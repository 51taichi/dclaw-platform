interface AgentRouteDecisionInput {
  previousAgent?: string;
  nextAgent?: string;
  currentChatId?: string | null;
}

export function shouldRedirectAfterAgentChange({
  previousAgent,
  nextAgent,
  currentChatId,
}: AgentRouteDecisionInput): boolean {
  if (!previousAgent || previousAgent === nextAgent) return false;
  return !currentChatId;
}
