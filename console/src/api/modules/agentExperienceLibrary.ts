import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";
import { ApiRequestError, request } from "../request";

export interface AgentExperiencePublication {
  id: string;
  public_id: string;
  name: string;
  target_type: "agent" | "expert_team";
  target_id: string;
  target_name: string;
  status: "enabled" | "disabled";
  knowledge_base_id: string;
}

export interface AgentExperienceDocument {
  id: string;
  name: string;
  source_type?: string;
  type?: string;
  size?: string;
  chunk_count?: number;
  slices?: number;
  status: string;
  updated_at?: string | null;
  updatedAt?: string | null;
  last_error?: string | null;
}

function publicationPath(publicationId: string) {
  return `/open-api-knowledge/publications/${encodeURIComponent(
    publicationId,
  )}`;
}

async function uploadDocument(publicationId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(
    getApiUrl(`${publicationPath(publicationId)}/docs`),
    {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new ApiRequestError(
      detail || `Request failed: ${response.status}`,
      response.status,
    );
  }
  return (await response.json()) as AgentExperienceDocument;
}

export const agentExperienceLibraryApi = {
  listPublications: () =>
    request<AgentExperiencePublication[]>("/open-api-knowledge/publications"),

  listDocuments: (publicationId: string) =>
    request<AgentExperienceDocument[]>(
      `${publicationPath(publicationId)}/docs`,
    ),

  uploadDocument,

  syncDocument: (publicationId: string, docId: string) =>
    request<AgentExperienceDocument>(
      `${publicationPath(publicationId)}/docs/${encodeURIComponent(
        docId,
      )}/sync`,
      { method: "POST" },
    ),

  deleteDocument: (publicationId: string, docId: string) =>
    request<{ deleted: boolean; id: string }>(
      `${publicationPath(publicationId)}/docs/${encodeURIComponent(docId)}`,
      { method: "DELETE" },
    ),
};
