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
