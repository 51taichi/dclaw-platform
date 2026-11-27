import type { AgentSummary } from "@/api/types/agents";

const LOCAL_SESSION = "local.execution.session/1";
const LOCAL_PREFLIGHT = "local.environment.preflight/1";

export type LocalAssistantMode = "none" | "optional" | "required";

export function localAssistantMode(agent?: AgentSummary): LocalAssistantMode {
  const capabilities = new Set(agent?.declared_capabilities ?? []);
  if (capabilities.has(LOCAL_PREFLIGHT)) return "required";
  if (capabilities.has(LOCAL_SESSION)) return "optional";
  return "none";
}
