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
    exportPricing: vi.fn(),
    unlockPricing: vi.fn(),
    previewPricingImport: vi.fn(),
    confirmPricingImport: vi.fn(),
    setPricingExclusion: vi.fn(),
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
    expect(screen.getByText(/先导出价格清单/)).toBeInTheDocument();
    expect(
      screen.getByText(/请导出当前启用模型的价格清单/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/先生成当前启用模型的价格草案/),
    ).not.toBeInTheDocument();
  });

  it("shows only the export-import-publish workflow", async () => {
    render(<PricingTab />);

    expect(await screen.findByText("导出价格清单")).toBeInTheDocument();
    expect(screen.getByText("导入Excel")).toBeInTheDocument();
    expect(screen.queryByText("同步官网价格")).not.toBeInTheDocument();
    expect(screen.queryByText("刷新官方候选")).not.toBeInTheDocument();
    expect(screen.queryByText("生成价格草案")).not.toBeInTheDocument();
    expect(screen.queryByText(/官网价格同步：/)).not.toBeInTheDocument();
    expect(billingApi.listPricingCollectionJobs).not.toHaveBeenCalled();
  });

  it("acknowledges an Excel file that was already approved", async () => {
    const user = userEvent.setup();
    vi.mocked(billingApi.unlockPricing).mockResolvedValue({
      token: "unlock-token",
      expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    });
    vi.mocked(billingApi.previewPricingImport).mockResolvedValue({
      id: "existing-import",
      status: "ready",
      rows: [],
      valid_rows: [
        {
          provider_id: "liuma",
          model_key: "gpt-5.6-sol",
          excluded: false,
        },
      ],
      pricing_preview: {
        publishable: true,
        blockers: [],
        review: {
          included_models: 1,
          included_dimensions: 2,
          excluded_models: 0,
          manual_dimensions: 2,
          rows: [],
        },
      },
    });
    vi.mocked(billingApi.confirmPricingImport).mockResolvedValue({
      id: "existing-import",
      status: "confirmed",
      already_confirmed: true,
    });

    render(<PricingTab />);
    await user.click(await screen.findByText("解锁计费设置"));
    await user.type(screen.getByLabelText("管理员密码"), "password");
    await user.click(screen.getByText("确认解锁"));

    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(
      input!,
      new File(["workbook"], "pricing-list.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(await screen.findByText("确认审批导入"));

    expect(
      await screen.findByText("该文件此前已审批导入，本次未重复创建价格草稿"),
    ).toBeInTheDocument();
  });

  it("counts durable draft catalogs in the draft tab", async () => {
    const overview = await vi.mocked(billingApi.getPricingOverview)();
    vi.mocked(billingApi.getPricingOverview).mockResolvedValue({
      ...overview,
      catalogs: [
        ...overview.catalogs,
        {
          id: "d1",
          version: "draft-1",
          status: "draft",
          effective_at: "2026-08-31",
          metadata: {},
          rules: [],
        },
        {
          id: "d2",
          version: "draft-2",
          status: "draft",
          effective_at: "2026-08-31",
          metadata: {},
          rules: [],
        },
      ],
    });

    render(<PricingTab />);

    expect(await screen.findByText("价格草稿 (2)")).toBeInTheDocument();
  });
});
