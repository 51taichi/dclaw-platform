import { request } from "../request";
import type {
  BillingLedgerEntry,
  BillingUsageOrder,
  BillingWallet,
  Page,
  SubmitTopUpClaim,
  TopUpClaim,
  TopUpConfig,
  TopUpProduct,
} from "../types/billing";

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

function idempotencyHeaders(key: string): Headers {
  return new Headers({ "Idempotency-Key": key });
}

export const billingApi = {
  getWallet: () => request<BillingWallet>("/billing/wallet"),
  listLedger: (params: { limit?: number; cursor?: string } = {}) =>
    request<Page<BillingLedgerEntry>>(`/billing/ledger${query(params)}`),
  listUsage: (params: Record<string, string | number | undefined> = {}) =>
    request<Page<BillingUsageOrder>>(`/billing/usage${query(params)}`),
  getUsage: (id: string) => request(`/billing/usage/${id}`),
  getSummary: (params: { date_from?: string; date_to?: string } = {}) =>
    request(`/billing/summary${query(params)}`),
  getTopUpConfig: () => request<TopUpConfig>("/billing/top-up/config"),
  listProducts: () => request<Page<TopUpProduct>>("/billing/top-up/products"),
  listClaims: () => request<Page<TopUpClaim>>("/billing/top-up/claims"),
  submitClaim: (payload: SubmitTopUpClaim, idempotencyKey: string) =>
    request<TopUpClaim>("/billing/top-up/claims", {
      method: "POST",
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify(payload),
    }),
  listAdminClaims: (
    params: { status?: TopUpClaim["status"]; limit?: number } = {},
  ) =>
    request<Page<TopUpClaim>>(`/admin/billing/top-up/claims${query(params)}`),
  approveClaim: (id: string, reason: string, idempotencyKey: string) =>
    request<TopUpClaim>(`/admin/billing/top-up/claims/${id}/approve`, {
      method: "POST",
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify({ reason }),
    }),
  rejectClaim: (id: string, reason: string, idempotencyKey: string) =>
    request<TopUpClaim>(`/admin/billing/top-up/claims/${id}/reject`, {
      method: "POST",
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify({ reason }),
    }),
  listAdminProducts: () =>
    request<Page<TopUpProduct>>("/admin/billing/top-up/products"),
  createProduct: (payload: Omit<TopUpProduct, "public_id">) =>
    request<TopUpProduct>("/admin/billing/top-up/products", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  replaceProduct: (id: string, payload: Omit<TopUpProduct, "public_id">) =>
    request<TopUpProduct>(`/admin/billing/top-up/products/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  listCatalogs: () => request<unknown[]>("/admin/billing/catalogs"),
  listAdminUsage: (params: Record<string, string | number | undefined> = {}) =>
    request<Page<Record<string, unknown>>>(
      `/admin/billing/usage-orders${query(params)}`,
    ),
  listReconciliation: () =>
    request<Page<Record<string, unknown>>>("/admin/billing/reconciliation"),
  listReconciliationAudits: () =>
    request<Page<Record<string, unknown>>>(
      "/admin/billing/reconciliation-audits",
    ),
  getRollout: () => request<Record<string, unknown>>("/admin/billing/rollout"),
  activateRollout: (mode: "off" | "shadow" | "observe" | "enforced") =>
    request<Record<string, unknown>>("/admin/billing/rollout/activate", {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
};
