import type { AgentSummary } from "../../api/types/agents";

export function clientVisibleAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter(
    (agent) => agent.agent_type === "sealed" || !agent.open_api_enabled,
  );
}
