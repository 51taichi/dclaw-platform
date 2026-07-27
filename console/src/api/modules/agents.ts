import { request } from "../request";
import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  AgentProfileRef,
  ReorderAgentsResponse,
  AgentPackagePreview,
  AgentPackageImportResult,
} from "../types/agents";

async function uploadAgentPackage<T>(
  endpoint: string,
  file: File,
  options?: {
    agent_id?: string;
    enabled?: boolean;
    mode?: "create" | "update";
  },
): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.agent_id) {
    formData.append("agent_id", options.agent_id);
  }
  if (options?.enabled !== undefined) {
    formData.append("enabled", String(options.enabled));
  }
  if (options?.mode) {
    formData.append("mode", options.mode);
  }

  const response = await fetch(getApiUrl(endpoint), {
    method: "POST",
    headers: buildAuthHeaders(),
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

// Multi-agent management API
export const agentsApi = {
  // List all agents
  listAgents: () => request<AgentListResponse>("/agents"),

  // Get agent details
  getAgent: (agentId: string) =>
    request<AgentProfileConfig>(`/agents/${agentId}`),

  // Create new agent
  createAgent: (agent: CreateAgentRequest) =>
    request<AgentProfileRef>("/agents", {
      method: "POST",
      body: JSON.stringify(agent),
    }),

  // Preview an exported agent package before import
  previewAgentPackage: (file: File, options?: { agent_id?: string }) =>
    uploadAgentPackage<AgentPackagePreview>(
      "/agents/import-package/preview",
      file,
      options,
    ),

  // Import an exported agent package as a configured agent
  importAgentPackage: (
    file: File,
    options?: {
      agent_id?: string;
      enabled?: boolean;
      mode?: "create" | "update";
    },
  ) =>
    uploadAgentPackage<AgentPackageImportResult>(
      "/agents/import-package",
      file,
      options,
    ),

  // Update agent configuration
  updateAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),

  // Delete agent
  deleteAgent: (agentId: string) =>
    request<{ success: boolean; agent_id: string }>(`/agents/${agentId}`, {
      method: "DELETE",
    }),

  // Persist ordered agent ids
  reorderAgents: (agentIds: string[]) =>
    request<ReorderAgentsResponse>("/agents/order", {
      method: "PUT",
      body: JSON.stringify({ agent_ids: agentIds }),
    }),

  // Toggle agent enabled state
  toggleAgentEnabled: (agentId: string, enabled: boolean) =>
    request<{ success: boolean; agent_id: string; enabled: boolean }>(
      `/agents/${agentId}/toggle`,
      {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      },
    ),
};
