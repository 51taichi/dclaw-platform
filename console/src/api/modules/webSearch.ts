import { request } from "../request";

export interface WebSearchConfig {
  provider: "aliyun_iqs";
  enabled: boolean;
  api_key: string;
  endpoint: string;
  engine_type: "LiteAdvanced";
  default_max_results: number;
  timeout_seconds: number;
  cache_ttl_seconds: number;
  configured: boolean;
  available: boolean;
  updated_at?: string;
}

export interface WebSearchTestResult {
  ok: boolean;
  provider: string;
  engine_type: string;
  result_count: number;
  request_id: string;
  latency_ms: number;
  sample_title: string;
}

export const webSearchApi = {
  getConfig: () =>
    request<{ config: WebSearchConfig }>("/admin/web-search/config"),

  updateConfig: (config: Partial<WebSearchConfig>) =>
    request<{ config: WebSearchConfig }>("/admin/web-search/config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  testConfig: (config: Partial<WebSearchConfig>) =>
    request<WebSearchTestResult>("/admin/web-search/test", {
      method: "POST",
      body: JSON.stringify(config),
    }),
};
