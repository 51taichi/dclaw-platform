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
              metadata: { input_rmb_sale_price: "0.0137" },
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
  });

  it("groups models and renders RMB without foreign currency", async () => {
    const user = userEvent.setup();
    render(<PricingTab />);
    await user.click(await screen.findByText("模型价格"));
    expect(await screen.findByText("百炼")).toBeInTheDocument();
    expect(screen.getByText("文本/多模态对话")).toBeInTheDocument();
    expect(screen.getByText(/¥0.0137/)).toBeInTheDocument();
    expect(screen.queryByText(/USD|美元/)).not.toBeInTheDocument();
  });
});
