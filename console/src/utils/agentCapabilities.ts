import type { AgentCapabilities, AgentSummary } from "../api/types/agents";

const standardCapabilities: AgentCapabilities = {
  invoke: true,
  public_metadata: true,
  inspect: true,
  edit: true,
  clone: true,
  export: true,
  download: true,
  trace: true,
};

export function capabilitiesForAgent(
  agent?: AgentSummary | null,
): AgentCapabilities {
  if (!agent) return standardCapabilities;
  if (agent.capabilities) return agent.capabilities;
  return agent.agent_type === "sealed"
    ? {
        invoke: true,
        public_metadata: true,
        inspect: false,
        edit: false,
        clone: false,
        export: false,
        download: false,
        trace: false,
      }
    : standardCapabilities;
}

export function canInspectAgent(agent?: AgentSummary | null): boolean {
  return capabilitiesForAgent(agent).inspect;
}
