import type { AgentSummary } from "../../api/types/agents";

export function clientVisibleAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter((agent) => !agent.open_api_enabled);
}
