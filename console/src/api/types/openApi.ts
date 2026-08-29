export type OpenApiTargetType = "agent" | "expert_team";
export type OpenApiPublicationStatus = "enabled" | "disabled";
export type OpenApiKeyStatus = "active" | "revoked";
export type OpenApiInvocationStatus =
  | "accepted"
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";
export type OpenApiScope = "messages:create" | "messages:read" | "runs:stop";

export const DEFAULT_OPEN_API_SCOPES: OpenApiScope[] = ["messages:create"];

export interface OpenApiPublication {
  id: string;
  public_id: string;
  target_type: OpenApiTargetType;
  target_id: string;
  owner_user_id?: string;
  bound_user_id: string;
  knowledge_base_id: string;
  title?: string;
  name?: string;
  description?: string;
  scopes?: OpenApiScope[];
  allowed_scopes?: OpenApiScope[];
  status: OpenApiPublicationStatus;
  created_at?: string | null;
  updated_at?: string | null;
  allowed_capability?: "standard" | "invoke_only";
  response_policy?: "standard" | "sealed";
}

export interface CreateOpenApiPublicationRequest {
  public_id: string;
  target_type: OpenApiTargetType;
  target_id: string;
  bound_user_id: number;
  title?: string;
  description?: string;
  scopes: OpenApiScope[];
  status: OpenApiPublicationStatus;
}

export interface UpdateOpenApiPublicationStatusRequest {
  status: OpenApiPublicationStatus;
}

export interface OpenApiExternalApp {
  id: string;
  owner_user_id?: string;
  name: string;
  status?: OpenApiPublicationStatus;
  ip_allowlist?: string[];
  quota_policy?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateOpenApiExternalAppRequest {
  name: string;
  ip_allowlist?: string[];
  quota_policy?: Record<string, unknown>;
}

export interface OpenApiKey {
  id: string;
  app_id: string;
  publication_id: string;
  name?: string;
  key_prefix?: string;
  key_suffix?: string;
  scopes: OpenApiScope[];
  status: OpenApiKeyStatus;
  expires_at?: string | null;
  last_used_at?: string | null;
  last_used_ip?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateOpenApiKeyRequest {
  app_id: string;
  publication_id: string;
  expires_at?: string | null;
  scopes: OpenApiScope[];
}

export interface CreateOpenApiKeyResponse {
  key: OpenApiKey;
  secret: string;
  plaintext_key?: string;
}

export interface OpenApiInvocation {
  id: string;
  app_id: string;
  publication_id: string;
  api_key_id: string;
  target_type: OpenApiTargetType;
  target_id: string;
  chat_id?: string | null;
  external_session_id?: string | null;
  external_user_id?: string | null;
  status: OpenApiInvocationStatus;
  status_code?: number | null;
  latency_ms?: number;
  token_summary?: Record<string, unknown>;
  error_summary?: string | null;
  created_at?: string | null;
}

export interface ListOpenApiKeysParams {
  app_id?: string;
  publication_id?: string;
}

export interface ListOpenApiInvocationsParams {
  publication_id?: string;
  limit?: number;
  offset?: number;
}
