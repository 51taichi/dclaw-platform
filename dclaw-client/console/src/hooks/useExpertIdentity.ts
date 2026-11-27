import { useEffect, useMemo, useState } from "react";
import { agentsApi } from "../api/modules/agents";
import type { AgentSummary } from "../api/types/agents";
import { expertIdentity } from "../utils/expertIdentity";

export function useExpertIdentity(agentId: string, isExpertTeam = false) {
  const [agent, setAgent] = useState<AgentSummary | null>(null);
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      agentsApi
        .listAgents({ excludeOpenApi: true })
        .then(({ agents }) => {
          if (!cancelled)
            setAgent(agents.find((item) => item.id === agentId) || null);
        })
        .catch(() => {
          if (!cancelled) setAgent(null);
        });
    };
    refresh();
    window.addEventListener("expert-avatar-updated", refresh);
    return () => {
      cancelled = true;
      window.removeEventListener("expert-avatar-updated", refresh);
    };
  }, [agentId]);
  return useMemo(
    () => expertIdentity(agent?.id === agentId && !isExpertTeam ? agent : null),
    [agent, agentId, isExpertTeam],
  );
}
