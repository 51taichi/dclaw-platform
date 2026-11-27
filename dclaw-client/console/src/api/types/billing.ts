export interface BillingWallet {
  available: number;
  held: number;
  purchased: number;
  promotional: number;
  package: number;
}

export interface CreditAlertPreferences {
  warning_threshold: number;
  critical_threshold: number;
}

export interface CreditAlert {
  tier: "warning" | "critical";
  threshold: number;
  available: number;
  triggered_at: string;
}

export interface CreditAlertResource {
  preferences: CreditAlertPreferences;
  available: number;
  alert: CreditAlert | null;
  phone_number: string | null;
}

export interface InsufficientCreditsFailure {
  code: "INSUFFICIENT_CREDITS";
  available_credits: number;
  required_credits: number;
  top_up_path: string;
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

export type BillingUsageSource =
  | "client"
  | "mobile"
  | "openapi"
  | "expert_team"
  | "automation"
  | "schedule"
  | "channel";

export type BillingUsageStatus = "quoted" | "held" | "settled" | "reconciling";

export interface BillingUsageItem {
  call_sequence: number;
  expert_role: string | null;
  model: string;
  provider: string;
  capability: string;
  tokens: { input: number; output: number };
  charged_credits: number;
  status: string;
  catalog_version: string;
}

export interface BillingReconciliationItem extends BillingUsageItem {
  quoted_credits: number;
  created_at: string;
  evidence: {
    supplier_reference_present: boolean;
    execution_outcome: string;
  };
}

export interface BillingReconciliationRecord {
  reconciliation_id: string;
  order: BillingUsageOrder;
  item: BillingReconciliationItem;
}

export interface BillingReconciliationResolution {
  billability: "billable" | "not_billable";
  reason: string;
  actual_input_tokens: number;
  actual_output_tokens: number;
}

export interface BillingReconciliationAudit {
  audit_id: string;
  reconciliation_id: string;
  order_id: string;
  actor_id: string;
  reason: string;
  idempotency_key: string;
  resolution: {
    status: "captured" | "released";
    billability: "billable" | "not_billable";
    actual_tokens: { input: number; output: number };
    charged_credits: number;
  };
  created_at: string;
}

export interface BillingUsageOrder {
  id: string;
  owner_user_id?: string;
  source: BillingUsageSource;
  expert: string | null;
  expert_team: string | null;
  status: BillingUsageStatus;
  billing_status: string;
  billing_mode: "off" | "shadow" | "observe" | "enforced";
  is_estimate: boolean;
  catalog_version: string;
  quoted_credits: number;
  captured_credits: number;
  released_credits: number;
  reconciling_credits: number;
  actual_debited_credits: number;
  call_count: number;
  credits: {
    held: number;
    captured: number;
    released: number;
    reconciling: number;
  };
  tokens: { input: number; output: number };
  created_at: string;
  updated_at: string;
  publication?: { id: string; name: string };
  application?: { id: string; name: string };
  invocation_id?: string | null;
  api_key_id?: string | null;
  items?: BillingUsageItem[];
}

export interface BillingUsageSummaryValues {
  orders: number;
  model_calls: number;
  input_tokens: number;
  output_tokens: number;
  retail_credits: number;
  actual_debited_credits: number;
  shadow_estimated_credits: number;
  reconciling_credits: number;
}

export interface BillingUsageSummary {
  window: {
    date_from: string;
    date_to: string;
    timezone: "UTC";
    lifetime: false;
  };
  totals: BillingUsageSummaryValues;
  by_day: Array<{ date: string } & BillingUsageSummaryValues>;
  by_month: Array<{
    month: string;
    orders: number;
    retail_credits: number;
    actual_debited_credits: number;
  }>;
}

export type PricingCategory =
  "text" | "image" | "video" | "audio" | "embedding_rerank" | "other";

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
  review?: {
    included_models: number;
    included_dimensions: number;
    excluded_models: number;
    manual_dimensions: number;
    rows: Array<Record<string, unknown>>;
  };
}

export interface PricingPolicyInput {
  scope_type: "global" | "provider" | "category" | "model";
  scope_key: string;
  multiplier_decimal: string;
  settings?: Record<string, unknown>;
  expected_revision: number;
}

export interface PricingPolicy extends Omit<
  PricingPolicyInput,
  "expected_revision"
> {
  id: string;
  revision: number;
}

export interface PricingImportPreview {
  id: string;
  status: "ready" | "blocked";
  rows: Array<Record<string, unknown>>;
  valid_rows: Array<Record<string, unknown>>;
  pricing_preview?: PricingPreview;
}

export interface PricingDraftCoverage {
  enabled_models: number;
  matched_models: number;
  missing_models: number;
  excluded_models: number;
  blocking_models: number;
}

export interface PricingDraftRisk {
  code: string;
  provider_id: string;
  model_key: string;
  unit_key?: string | null;
}

export interface PricingDraftRow {
  provider_id: string;
  provider_name: string;
  model_key: string;
  model_name: string;
  official_provider_id?: string | null;
  official_model_id?: string | null;
  category: PricingCategory;
  capability: string;
  unit_key: string;
  unit_size: number;
  conditions: Record<string, unknown>;
  rmb_cost?: string | number | null;
  multiplier: string | number;
  rmb_sale_price?: string | number | null;
  credits?: number | null;
  source_type: string;
  source_url?: string | null;
  verification_status: string;
  include_in_publish: boolean;
  exclusion_reason?: string | null;
  registry_version?: string | null;
  evidence_level?: string | null;
  evidence_excerpt?: string | null;
  confidence?: string | number | null;
  ai_model?: string | null;
}

export interface PricingDraft {
  draft_key: string;
  coverage: PricingDraftCoverage;
  rows: PricingDraftRow[];
  risks: PricingDraftRisk[];
}

export interface PricingCollectionItem {
  id: string;
  provider_id: string;
  model_key: string;
  pricing_region: string;
  status: string;
  error_summary?: string | null;
  result?: Record<string, unknown>;
}

export interface PricingCollectionJob {
  id: string;
  status:
    "pending" | "running" | "succeeded" | "partially_succeeded" | "failed";
  progress: Partial<{
    total: number;
    completed: number;
    pending: number;
    running: number;
    official: number;
    ai: number;
    manual: number;
    failed: number;
  }>;
  items?: PricingCollectionItem[];
  error_summary?: string | null;
}

export interface PricingModelMapping {
  id: string;
  provider_id: string;
  model_key: string;
  official_provider_id: string;
  official_model_id: string;
  revision: number;
}
