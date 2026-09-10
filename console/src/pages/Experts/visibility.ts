import type { AgentSummary } from "../../api/types/agents";

export function clientVisibleAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter(
    (agent) =>
      agent.enabled !== false &&
      (agent.agent_type === "sealed" || !agent.open_api_enabled),
  );
}
