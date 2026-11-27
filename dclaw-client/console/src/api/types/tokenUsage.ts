/** Single token usage record (per date + provider + model). */
export interface TokenUsageRecord {
  date: string; // YYYY-MM-DD
  provider_id: string;
  model: string;
  user_id?: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

/** Per-model (has provider_id, model) or per-date (no provider_id, model) stats. */
export interface TokenUsageStats {
  provider_id?: string;
  model?: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

export interface TokenUsageSummary {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_calls: number;
  by_model: Record<string, TokenUsageStats>;
  by_date: Record<string, TokenUsageStats>;
}

export type CreditRankingPeriodType = "year" | "month" | "week" | "day";

export interface CreditConsumptionRankingItem {
  rank: number;
  user_id: string;
  username: string;
  consumed_credits: number;
  call_count: number;
}

export interface CreditConsumptionRankingResponse {
  items: CreditConsumptionRankingItem[];
  page: number;
  page_size: number;
  total: number;
  period: {
    type: CreditRankingPeriodType;
    anchor_date: string;
    started_at: string;
    ended_at: string;
    timezone: "Asia/Shanghai";
  };
}
