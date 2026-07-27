import { request } from "../request";
import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";
import type {
  CreateOpenApiExternalAppRequest,
  CreateOpenApiKeyRequest,
  CreateOpenApiKeyResponse,
  CreateOpenApiPublicationRequest,
  ListOpenApiInvocationsParams,
  ListOpenApiKeysParams,
  OpenApiExternalApp,
  OpenApiInvocation,
  OpenApiKey,
  OpenApiKnowledgeDocument,
  OpenApiPublication,
  OpenApiPublicationStatus,
} from "../types/openApi";

async function uploadPublicationKnowledge(
  publicationId: string,
  file: File,
): Promise<OpenApiKnowledgeDocument> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(
    getApiUrl(`/open-api/publications/${publicationId}/knowledge/docs`),
    {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as OpenApiKnowledgeDocument;
}

function buildQuery(params: object) {
  const query = new URLSearchParams();
  Object.entries(params as Record<string, string | number | undefined>).forEach(
    ([key, value]) => {
      if (value !== undefined && value !== "") {
        query.set(key, String(value));
      }
    },
  );
  const text = query.toString();
  return text ? `?${text}` : "";
}

export const openApiApi = {
  listPublications: () =>
    request<OpenApiPublication[]>("/open-api/publications"),

  createPublication: (payload: CreateOpenApiPublicationRequest) =>
    request<OpenApiPublication>("/open-api/publications", {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        name: payload.title || payload.public_id,
        allowed_scopes: payload.scopes,
      }),
    }),

  updatePublicationStatus: (
    publicationId: string,
    status: OpenApiPublicationStatus,
  ) =>
    request<OpenApiPublication>(
      `/open-api/publications/${publicationId}/status`,
      {
        method: "PATCH",
        body: JSON.stringify({ status }),
      },
    ),

  listKnowledgeDocuments: (publicationId: string) =>
    request<OpenApiKnowledgeDocument[]>(
      `/open-api/publications/${publicationId}/knowledge/docs`,
    ),

  uploadKnowledgeDocument: (publicationId: string, file: File) =>
    uploadPublicationKnowledge(publicationId, file),

  syncKnowledgeDocument: (publicationId: string, docId: string) =>
    request<OpenApiKnowledgeDocument>(
      `/open-api/publications/${publicationId}/knowledge/docs/${docId}/sync`,
      { method: "POST" },
    ),

  deleteKnowledgeDocument: (publicationId: string, docId: string) =>
    request<{ deleted: boolean; id: string }>(
      `/open-api/publications/${publicationId}/knowledge/docs/${docId}`,
      { method: "DELETE" },
    ),

  listApps: () => request<OpenApiExternalApp[]>("/open-api/apps"),

  createApp: (payload: CreateOpenApiExternalAppRequest) =>
    request<OpenApiExternalApp>("/open-api/apps", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listKeys: (params: ListOpenApiKeysParams = {}) =>
    request<OpenApiKey[]>(`/open-api/keys${buildQuery(params)}`),

  createKey: async (
    payload: CreateOpenApiKeyRequest,
  ): Promise<CreateOpenApiKeyResponse> => {
    const response = await request<CreateOpenApiKeyResponse>("/open-api/keys", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return {
      ...response,
      secret: response.secret || response.plaintext_key || "",
    };
  },

  revokeKey: (keyId: string) =>
    request<OpenApiKey>(`/open-api/keys/${keyId}/revoke`, {
      method: "POST",
    }),

  listInvocations: (params: ListOpenApiInvocationsParams = {}) =>
    request<OpenApiInvocation[]>(`/open-api/invocations${buildQuery(params)}`),
};
