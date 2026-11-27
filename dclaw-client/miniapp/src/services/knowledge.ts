import { request } from "./api";

export interface KnowledgeHit {
  id?: string;
  title?: string;
  source?: string;
  snippet?: string;
  score?: number;
}

export interface KnowledgeSearchResponse {
  hits: KnowledgeHit[];
  semantic_enabled?: boolean;
  keyword_enabled?: boolean;
}

export function searchKnowledge(q: string, scope = "all", topK = 5) {
  const query = encodeURIComponent(q);
  return request<KnowledgeSearchResponse>(
    `/workspace/knowledge/search?q=${query}&scope=${scope}&top_k=${topK}`,
  );
}
