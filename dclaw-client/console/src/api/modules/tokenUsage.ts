import { request } from "../request";
import type {
  CreditConsumptionRankingResponse,
  CreditRankingPeriodType,
  TokenUsageSummary,
  TokenUsageRecord,
} from "../types/tokenUsage";

export interface GetTokenUsageParams {
  start_date: string;
  end_date: string;
  model?: string;
  provider?: string;
}

export interface GetCreditConsumptionRankingParams {
  period: CreditRankingPeriodType;
  anchor_date: string;
  page: number;
  page_size: number;
}

function buildQuery(params: GetTokenUsageParams): string {
  const search = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  if (params.model) search.set("model", params.model);
  if (params.provider) search.set("provider", params.provider);
  return `?${search.toString()}`;
}

export const tokenUsageApi = {
  getCreditConsumptionRanking: (params: GetCreditConsumptionRankingParams) => {
    const search = new URLSearchParams({
      period: params.period,
      anchor_date: params.anchor_date,
      page: String(params.page),
      page_size: String(params.page_size),
    });
    return request<CreditConsumptionRankingResponse>(
      `/admin/billing/credit-consumption-ranking?${search.toString()}`,
    );
  },

  // Original summary endpoint (backend aggregation)
  getTokenUsage: (params: GetTokenUsageParams) =>
    request<TokenUsageSummary>(`/admin/token-usage${buildQuery(params)}`),

  // New details endpoint (raw records for frontend aggregation)
  getTokenUsageDetails: (params: GetTokenUsageParams) =>
    request<TokenUsageRecord[]>(
      `/admin/token-usage/details${buildQuery(params)}`,
    ),
};
