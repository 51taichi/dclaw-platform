export interface BillingWallet {
  available: number;
  held: number;
  purchased: number;
  promotional: number;
  package: number;
}

export interface TopUpProduct {
  public_id: string;
  name: string;
  description: string | null;
  payment_amount_fen: number;
  purchased_credits: number;
  promotional_credits: number;
  promotional_expiry_days: number | null;
  status: "active" | "disabled";
  display_order: number;
}

export interface TopUpClaim {
  public_id: string;
  product_snapshot: TopUpProduct;
  payment_amount_fen: number;
  payment_channel: "wechat" | "alipay" | "bank" | "other";
  payer_reference: string;
  customer_note: string | null;
  status: "pending" | "approved" | "rejected";
  review_reason: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  owner_id?: string;
  reviewed_by?: string | null;
}

export interface TopUpConfig {
  enabled: boolean;
  qr_url: string | null;
  instructions: string;
}

export interface SubmitTopUpClaim {
  product_id: string;
  payment_channel: TopUpClaim["payment_channel"];
  payer_reference: string;
  customer_note?: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

export interface BillingLedgerEntry {
  id: string;
  event_type: string;
  status: string;
  credit_delta: number;
  cash_delta_fen: number;
  business_type: string;
  metadata: Record<string, string | number | boolean | null>;
  created_at: string;
}

export interface BillingUsageOrder {
  id: string;
  status: string;
  provider_id: string;
  model_key: string;
  capability: string;
  quoted_credits: number;
  captured_credits: number;
  created_at: string;
}

export type PricingCategory =
  | "text"
  | "image"
  | "video"
  | "audio"
  | "embedding_rerank"
  | "other";

export interface PricingCatalogSummary {
  id: string;
  version: string;
  status: "draft" | "published";
  effective_at: string;
  published_at?: string | null;
  metadata: Record<string, unknown>;
  rules?: PricingRuleSummary[];
}

export interface PricingRuleSummary {
  id: string;
  provider_id: string;
  model_key: string;
  capability: string;
  unit_type: string;
  credits_per_unit: number;
  input_credits_per_1k: number;
  output_credits_per_1k: number;
  metadata: Record<string, unknown>;
}

export interface PricingOverview {
  enabled_models: number;
  covered_models: number;
  catalogs: PricingCatalogSummary[];
}

export interface PriceableModel {
  provider_id: string;
  provider_name: string;
  model_key: string;
  model_name: string;
  category: PricingCategory;
}

export interface PricingAudit {
  id: string;
  action: string;
  actor_id: string;
  before_json: string;
  after_json: string;
  created_at: string;
}

export interface PricingUnlock {
  token: string;
  expires_at: string;
}

export interface PricingPreview {
  publishable: boolean;
  catalog_id?: string;
  version?: string;
  rule_count?: number;
  blockers: Array<{
    code: string;
    provider_id: string;
    model_key: string;
    unit_key: string;
  }>;
}

export interface PricingPolicyInput {
  scope_type: "global" | "provider" | "category" | "model";
  scope_key: string;
  multiplier_decimal: string;
  settings?: Record<string, unknown>;
  expected_revision: number;
}

export interface PricingImportPreview {
  id: string;
  status: "ready" | "blocked";
  rows: Array<Record<string, unknown>>;
  valid_rows: Array<Record<string, unknown>>;
}
