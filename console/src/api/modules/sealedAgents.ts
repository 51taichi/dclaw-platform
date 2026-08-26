import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";
import { request } from "../request";
import type { AgentCapabilities } from "../types/agents";

export interface SealedRelease {
  release_id: string;
  version: string;
  content_digest: string;
  signer_id: string;
  state: string;
  installed_at: string;
}

export interface SealedAgentOperational {
  agent_id: string;
  name: string;
  description: string;
  enabled: boolean;
  availability: "available" | "unavailable";
  active_release_id?: string | null;
  version?: string | null;
  signer_id?: string | null;
  content_digest?: string | null;
  releases: SealedRelease[];
  capabilities: AgentCapabilities;
}

export const sealedAgentsApi = {
  list: () => request<SealedAgentOperational[]>("/sealed-agents"),
  uploadRelease: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(getApiUrl("/sealed-agents/releases"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body,
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  },
  activate: (agentId: string, releaseId: string) =>
    request<SealedAgentOperational>(
      `/sealed-agents/${encodeURIComponent(
        agentId,
      )}/releases/${encodeURIComponent(releaseId)}/activate`,
      { method: "POST" },
    ),
  setEnabled: (agentId: string, enabled: boolean) =>
    request<SealedAgentOperational>(
      `/sealed-agents/${encodeURIComponent(agentId)}/${
        enabled ? "enable" : "disable"
      }`,
      { method: "POST" },
    ),
};
