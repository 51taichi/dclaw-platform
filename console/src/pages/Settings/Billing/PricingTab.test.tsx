import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../../api/modules/billing";
import PricingTab from "./PricingTab";

vi.mock("../../../api/modules/billing", () => ({
  billingApi: {
    getPricingOverview: vi.fn(),
    listPricingModels: vi.fn(),
    listPricingHistory: vi.fn(),
    listPricingPolicies: vi.fn(),
    listPricingModelMappings: vi.fn(),
    generatePricingDraft: vi.fn(),
    exportPricingDraft: vi.fn(),
    setPricingExclusion: vi.fn(),
    refreshOfficialPricingCandidates: vi.fn(),
    startPricingCollection: vi.fn(),
    getPricingCollectionJob: vi.fn(),
    listPricingCollectionJobs: vi.fn(),
    savePricingModelMapping: vi.fn(),
  },
}));

describe("PricingTab", () => {
  beforeEach(() => {
    vi.mocked(billingApi.getPricingOverview).mockResolvedValue({
      enabled_models: 1,
      covered_models: 1,
      catalogs: [
        {
          id: "c1",
          version: "retail-v1",
          status: "published",
          effective_at: "2026-08-30",
          metadata: {},
          rules: [
            {
              id: "r1",
              provider_id: "dashscope",
              model_key: "qwen-plus",
              capability: "chat",
              unit_type: "tokens",
              credits_per_unit: 0,
              input_credits_per_1k: 2,
              output_credits_per_1k: 4,
              metadata: {
                input_rmb_cost: "0.0100",
                input_rmb_sale_price: "0.0137",
                output_rmb_cost: "0.0200",
                output_rmb_sale_price: "0.0273",
                risk_buffer: "0.05",
                applied_multiplier: "1.3",
                multiplier_scope: "provider",
                multiplier_scope_key: "dashscope",
              },
            },
          ],
        },
      ],
    });
    vi.mocked(billingApi.listPricingModels).mockResolvedValue([
      {
        provider_id: "dashscope",
        provider_name: "百炼",
        model_key: "qwen-plus",
        model_name: "Qwen Plus",
        category: "text",
      },
    ]);
    vi.mocked(billingApi.listPricingHistory).mockResolvedValue([]);
    vi.mocked(billingApi.listPricingPolicies).mockResolvedValue([]);
    vi.mocked(billingApi.listPricingModelMappings).mockResolvedValue([]);
    vi.mocked(billingApi.listPricingCollectionJobs).mockResolvedValue([]);
  });

  it("groups models and renders RMB without foreign currency", async () => {
    const user = userEvent.setup();
    render(<PricingTab />);
    await user.click(await screen.findByText("模型价格"));
    expect(await screen.findByText("百炼")).toBeInTheDocument();
    expect(screen.getByText("文本/多模态对话")).toBeInTheDocument();
    expect(screen.getByText(/¥0.0137/)).toBeInTheDocument();
    expect(screen.getByText(/输出：成本 ¥0.0200/)).toBeInTheDocument();
    expect(screen.getByText(/售价 ¥0.0273/)).toBeInTheDocument();
    expect(screen.queryByText(/USD|美元/)).not.toBeInTheDocument();
  });

  it("shows the first catalog workflow and draft coverage", async () => {
    vi.mocked(billingApi.getPricingOverview).mockResolvedValue({
      enabled_models: 2,
      covered_models: 0,
      catalogs: [],
    });
    vi.mocked(billingApi.generatePricingDraft).mockResolvedValue({
      draft_key: "draft-1",
      coverage: {
        enabled_models: 2,
        matched_models: 1,
        missing_models: 1,
        excluded_models: 0,
        blocking_models: 1,
      },
      rows: [],
      risks: [
        {
          code: "official_price_missing",
          provider_id: "volcengine-cn",
          model_key: "missing-model",
        },
      ],
    });

    render(<PricingTab />);

    expect(await screen.findByText("尚未发布价格目录")).toBeInTheDocument();
    expect(screen.getByText(/默认按官方成本的 1.5 倍/)).toBeInTheDocument();
    expect(screen.getByText(/1 元人民币 = 100 积分/)).toBeInTheDocument();
  });

  it("shows durable official price collection progress without unlock", async () => {
    vi.mocked(billingApi.startPricingCollection).mockResolvedValue({
      id: "job-1",
      status: "pending",
      progress: {},
      items: [],
    });
    const user = userEvent.setup();
    render(<PricingTab />);

    await user.click(await screen.findByText("同步官网价格"));

    expect(
      await screen.findByText(/官网价格同步任务已提交/),
    ).toBeInTheDocument();
    expect(billingApi.startPricingCollection).toHaveBeenCalledOnce();
  });
});
