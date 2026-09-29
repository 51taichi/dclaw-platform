import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "./billing";

describe("billingApi", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "token"),
      removeItem: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ items: [] }),
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("routes customer and admin billing through separate namespaces", async () => {
    await billingApi.getWallet();
    await billingApi.listAdminClaims({ limit: 20 });

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/api/user/billing/wallet",
    );
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain(
      "/api/admin/billing/top-up/claims?limit=20",
    );
  });

  it("uses the customer credit alert contracts", async () => {
    await billingApi.getCreditAlerts();
    await billingApi.updateCreditAlertPreferences({
      warning_threshold: 6000,
      critical_threshold: 1200,
    });
    await billingApi.dismissCreditAlert("critical");

    const calls = vi.mocked(fetch).mock.calls;
    expect(String(calls[0][0])).toContain("/api/user/billing/credit-alerts");
    expect(calls[0][1]?.method).toBeUndefined();
    expect(String(calls[1][0])).toContain("/api/user/billing/credit-alerts/preferences");
    expect(calls[1][1]?.method).toBe("PATCH");
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({
      warning_threshold: 6000,
      critical_threshold: 1200,
    });
    expect(String(calls[2][0])).toContain("/api/user/billing/credit-alerts/critical/dismiss");
    expect(calls[2][1]?.method).toBe("POST");
  });

  it("submits only customer evidence with an idempotency header", async () => {
    await billingApi.submitClaim(
      {
        product_id: "opaque-product",
        payment_channel: "wechat",
        payer_reference: "tail-1234",
        customer_note: "paid",
      },
      "claim-key",
    );

    const options = vi.mocked(fetch).mock.calls[0][1];
    expect(options?.method).toBe("POST");
    expect(JSON.parse(String(options?.body))).toEqual({
      product_id: "opaque-product",
      payment_channel: "wechat",
      payer_reference: "tail-1234",
      customer_note: "paid",
    });
    expect((options?.headers as Headers).get("Idempotency-Key")).toBe(
      "claim-key",
    );
  });

  it("uses the server's durable usage and UTC summary routes", async () => {
    await billingApi.listUsage({ limit: 10, source: "expert_team" });
    await billingApi.getSummary({
      date_from: "2026-08-01",
      date_to: "2026-08-29",
    });
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/api/user/billing/usage-orders?limit=10&source=expert_team",
    );
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain(
      "/api/user/billing/open-api-summary?date_from=2026-08-01&date_to=2026-08-29",
    );
  });

  it("sends the scoped billing unlock only on pricing mutations", async () => {
    await billingApi.publishPricingPreview("draft-1", "unlock-token");
    const options = vi.mocked(fetch).mock.calls[0][1];
    expect(options?.method).toBe("POST");
    expect((options?.headers as Headers).get("X-Billing-Unlock")).toBe(
      "unlock-token",
    );

    await billingApi.getPricingOverview();
    const readOptions = vi.mocked(fetch).mock.calls[1][1];
    expect((readOptions?.headers as Headers).has("X-Billing-Unlock")).toBe(
      false,
    );
  });

  it("uses the draft, workbook, exclusion and refresh contracts", async () => {
    await billingApi.generatePricingDraft();
    await billingApi.exportPricingDraft("draft key");
    await billingApi.setPricingExclusion(
      "draft key",
      "volcengine-cn",
      "model/x",
      true,
      "no verified price",
      "unlock-token",
    );
    await billingApi.refreshOfficialPricingCandidates("unlock-token");

    const calls = vi.mocked(fetch).mock.calls;
    expect(String(calls[0][0])).toContain("/api/admin/billing/pricing/drafts");
    expect(calls[0][1]?.method).toBe("POST");
    expect(String(calls[1][0])).toContain("/pricing/drafts/draft%20key/export");
    expect(String(calls[2][0])).toContain(
      "/exclusions/volcengine-cn/model%2Fx",
    );
    expect(calls[2][1]?.method).toBe("PUT");
    expect(JSON.parse(String(calls[2][1]?.body))).toEqual({
      excluded: true,
      reason: "no verified price",
    });
    expect(String(calls[3][0])).toContain(
      "/pricing/official-candidates/refresh",
    );
  });

  it("starts and reads durable pricing collection jobs without unlock", async () => {
    await billingApi.startPricingCollection();
    await billingApi.getPricingCollectionJob("job/1");
    await billingApi.listPricingCollectionJobs();

    const calls = vi.mocked(fetch).mock.calls;
    expect(String(calls[0][0])).toContain("/pricing/collection-jobs");
    expect(calls[0][1]?.method).toBe("POST");
    expect(String(calls[1][0])).toContain("/pricing/collection-jobs/job%2F1");
    expect(String(calls[2][0])).toContain("/pricing/collection-jobs");
  });

  it("saves an explicit per-model publication decision", async () => {
    await billingApi.setPricingModelDecisions(
      "draft-1",
      [
        {
          provider_id: "dashscope",
          model_key: "qwen-plus",
          include_in_publish: false,
          reason: "本次不上线",
        },
      ],
      "unlock-token",
    );

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/pricing/drafts/draft-1/model-decisions");
    expect(options?.method).toBe("PUT");
    expect((options?.headers as Headers).get("X-Billing-Unlock")).toBe(
      "unlock-token",
    );
  });
});
