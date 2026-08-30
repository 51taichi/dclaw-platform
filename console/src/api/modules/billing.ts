import { request } from "../request";
import type {
  BillingLedgerEntry,
  BillingUsageOrder,
  BillingUsageSummary,
  BillingWallet,
  Page,
  SubmitTopUpClaim,
  TopUpClaim,
  TopUpConfig,
  TopUpProduct,
  PricingAudit,
  PricingCatalogSummary,
  PriceableModel,
  PricingImportPreview,
  PricingOverview,
  PricingModelMapping,
  PricingPolicyInput,
  PricingPolicy,
  PricingPreview,
  PricingUnlock,
  PricingDraft,
  PricingCollectionJob,
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

function pricingHeaders(token: string): Headers {
  return new Headers({ "X-Billing-Unlock": token });
}

export const billingApi = {
  getWallet: () => request<BillingWallet>("/billing/wallet"),
  listLedger: (params: { limit?: number; cursor?: string } = {}) =>
    request<Page<BillingLedgerEntry>>(`/billing/ledger${query(params)}`),
  listUsage: (params: Record<string, string | number | undefined> = {}) =>
    request<Page<BillingUsageOrder>>(`/billing/usage-orders${query(params)}`),
  getUsage: (id: string) =>
    request<BillingUsageOrder>(`/billing/usage-orders/${id}`),
  getSummary: (params: { date_from?: string; date_to?: string } = {}) =>
    request<BillingUsageSummary>(`/billing/open-api-summary${query(params)}`),
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
  getPricingOverview: () =>
    request<PricingOverview>("/admin/billing/pricing/overview"),
  listPricingModels: () =>
    request<PriceableModel[]>("/admin/billing/pricing/models"),
  listPricingHistory: () =>
    request<PricingAudit[]>("/admin/billing/pricing/history"),
  listPricingPolicies: () =>
    request<PricingPolicy[]>("/admin/billing/pricing/policies"),
  listPricingModelMappings: () =>
    request<PricingModelMapping[]>("/admin/billing/pricing/model-mappings"),
  exportPricing: () => request<Blob>("/admin/billing/pricing/export"),
  generatePricingDraft: () =>
    request<PricingDraft>("/admin/billing/pricing/drafts", {
      method: "POST",
    }),
  startPricingCollection: () =>
    request<PricingCollectionJob>("/admin/billing/pricing/collection-jobs", {
      method: "POST",
    }),
  listPricingCollectionJobs: () =>
    request<PricingCollectionJob[]>("/admin/billing/pricing/collection-jobs"),
  getPricingCollectionJob: (jobId: string) =>
    request<PricingCollectionJob>(
      `/admin/billing/pricing/collection-jobs/${encodeURIComponent(jobId)}`,
    ),
  setPricingModelDecisions: (
    draftKey: string,
    decisions: Array<{
      provider_id: string;
      model_key: string;
      include_in_publish: boolean;
      reason: string | null;
    }>,
    token: string,
  ) =>
    request(
      `/admin/billing/pricing/drafts/${encodeURIComponent(
        draftKey,
      )}/model-decisions`,
      {
        method: "PUT",
        headers: pricingHeaders(token),
        body: JSON.stringify({ decisions }),
      },
    ),
  batchSetPricingModelDecision: (
    draftKey: string,
    payload: {
      include_in_publish: boolean;
      provider_ids?: string[];
      evidence_levels?: string[];
      model_keys?: string[];
      reason?: string | null;
    },
    token: string,
  ) =>
    request(
      `/admin/billing/pricing/drafts/${encodeURIComponent(
        draftKey,
      )}/batch-decision`,
      {
        method: "POST",
        headers: pricingHeaders(token),
        body: JSON.stringify(payload),
      },
    ),
  exportPricingDraft: (draftKey: string) =>
    request<Blob>(
      `/admin/billing/pricing/drafts/${encodeURIComponent(draftKey)}/export`,
    ),
  setPricingExclusion: (
    draftKey: string,
    providerId: string,
    modelKey: string,
    excluded: boolean,
    reason: string | null,
    token: string,
  ) =>
    request(
      `/admin/billing/pricing/drafts/${encodeURIComponent(
        draftKey,
      )}/exclusions/${encodeURIComponent(providerId)}/${encodeURIComponent(
        modelKey,
      )}`,
      {
        method: "PUT",
        headers: pricingHeaders(token),
        body: JSON.stringify({ excluded, reason }),
      },
    ),
  savePricingModelMapping: (
    providerId: string,
    modelKey: string,
    officialProviderId: string,
    officialModelId: string,
    expectedRevision: number,
    token: string,
  ) =>
    request<PricingModelMapping>(
      `/admin/billing/pricing/model-mappings/${encodeURIComponent(
        providerId,
      )}/${encodeURIComponent(modelKey)}`,
      {
        method: "PUT",
        headers: pricingHeaders(token),
        body: JSON.stringify({
          official_provider_id: officialProviderId,
          official_model_id: officialModelId,
          expected_revision: expectedRevision,
        }),
      },
    ),
  refreshOfficialPricingCandidates: (token: string) =>
    request<{ candidate_count: number; registry_versions: string[] }>(
      "/admin/billing/pricing/official-candidates/refresh",
      { method: "POST", headers: pricingHeaders(token) },
    ),
  unlockPricing: (password: string) =>
    request<PricingUnlock>("/admin/billing/pricing/unlock", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  savePricingPolicy: (payload: PricingPolicyInput, token: string) =>
    request("/admin/billing/pricing/policies", {
      method: "POST",
      headers: pricingHeaders(token),
      body: JSON.stringify({ ...payload, settings: payload.settings ?? {} }),
    }),
  initializePricingPreview: (token: string) =>
    request<PricingPreview>("/admin/billing/pricing/initialize/preview", {
      method: "POST",
      headers: pricingHeaders(token),
    }),
  publishPricingPreview: (id: string, token: string) =>
    request<PricingCatalogSummary>(
      `/admin/billing/pricing/previews/${id}/publish`,
      { method: "POST", headers: pricingHeaders(token) },
    ),
  rollbackPricingCatalog: (id: string, token: string) =>
    request<PricingCatalogSummary>(
      `/admin/billing/pricing/catalogs/${id}/rollback`,
      { method: "POST", headers: pricingHeaders(token) },
    ),
  previewPricingImport: (file: File) =>
    request<PricingImportPreview>(
      `/admin/billing/pricing/imports/preview?filename=${encodeURIComponent(
        file.name,
      )}`,
      {
        method: "POST",
        headers: new Headers({ "Content-Type": file.type }),
        body: file,
      },
    ),
  confirmPricingImport: (id: string, token: string) =>
    request(`/admin/billing/pricing/imports/${id}/confirm`, {
      method: "POST",
      headers: pricingHeaders(token),
    }),
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
