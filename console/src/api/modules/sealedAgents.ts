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

export interface SealedReleaseUploadResult {
  agent_id: string;
  release_id: string;
  package_type: "sealed_agent" | "super_expert";
  signer_id: string;
}

export interface SuperExpertGrantPreview {
  preview_id: string;
  tenant_id: string;
  agent_id: string;
  release_id: string;
  package_digest: string;
  package_version: string;
  capability_digest: string;
  capabilities: [string, string][];
}

export interface SealedAgentOperational {
  avatar?: string | null;
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
  list: () => request<SealedAgentOperational[]>("/admin/sealed-agents"),
  uploadRelease: async (file: File): Promise<SealedReleaseUploadResult> => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(getApiUrl("/admin/sealed-agents/releases"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body,
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  },
  uploadAvatar: async (
    agentId: string,
    file: File,
  ): Promise<SealedAgentOperational> => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(
      getApiUrl(`/admin/sealed-agents/${encodeURIComponent(agentId)}/avatar`),
      {
        method: "POST",
        headers: buildAuthHeaders(),
        body,
      },
    );
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  },
  previewGrant: (agentId: string, releaseId: string) =>
    request<SuperExpertGrantPreview>(
      `/admin/sealed-agents/${encodeURIComponent(
        agentId,
      )}/releases/${encodeURIComponent(releaseId)}/grant-preview`,
    ),
  acceptGrant: (agentId: string, releaseId: string) =>
    request(
      `/admin/sealed-agents/${encodeURIComponent(
        agentId,
      )}/releases/${encodeURIComponent(releaseId)}/grant`,
      { method: "POST" },
    ),
  cancelGrant: (agentId: string, releaseId: string) =>
    request(
      `/admin/sealed-agents/${encodeURIComponent(
        agentId,
      )}/releases/${encodeURIComponent(releaseId)}/grant-cancel`,
      { method: "POST" },
    ),
  activate: (agentId: string, releaseId: string) =>
    request<SealedAgentOperational>(
      `/admin/sealed-agents/${encodeURIComponent(
        agentId,
      )}/releases/${encodeURIComponent(releaseId)}/activate`,
      { method: "POST" },
    ),
  setEnabled: (agentId: string, enabled: boolean) =>
    request<SealedAgentOperational>(
      `/admin/sealed-agents/${encodeURIComponent(agentId)}/${
        enabled ? "enable" : "disable"
      }`,
      { method: "POST" },
    ),
};
