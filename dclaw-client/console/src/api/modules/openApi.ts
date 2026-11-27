import { request } from "../request";
import type {
  CreateOpenApiExternalAppRequest,
  CreateOpenApiKeyRequest,
  CreateOpenApiKeyResponse,
  CreateOpenApiPublicationRequest,
  ListOpenApiInvocationsParams,
  ListOpenApiKeysParams,
  OpenApiExternalApp,
  OpenApiFallbackModelConfig,
  OpenApiFallbackModelOption,
  OpenApiInvocation,
  OpenApiKey,
  OpenApiPublication,
  OpenApiPublicationStatus,
} from "../types/openApi";

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
  getFallbackModel: () =>
    request<OpenApiFallbackModelConfig>("/open-api/fallback-model"),

  listFallbackModelOptions: () =>
    request<OpenApiFallbackModelOption[]>("/open-api/fallback-model/options"),

  updateFallbackModel: (payload: OpenApiFallbackModelConfig) =>
    request<OpenApiFallbackModelConfig>("/open-api/fallback-model", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

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

  updatePublicationBoundUser: (publicationId: string, boundUserId: number) =>
    request<OpenApiPublication>(
      `/open-api/publications/${publicationId}/bound-user`,
      {
        method: "PATCH",
        body: JSON.stringify({ bound_user_id: boundUserId }),
      },
    ),

  deletePublication: (publicationId: string) =>
    request<{ deleted: boolean; id: string }>(
      `/open-api/publications/${publicationId}`,
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
