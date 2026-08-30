import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PricingDrafts from "./PricingDrafts";

describe("PricingDrafts", () => {
  it("renders every tier with a distinct unit and condition identity", () => {
    render(
      <PricingDrafts
        catalogs={[]}
        draft={{
          draft_key: "draft",
          coverage: {
            enabled_models: 1,
            matched_models: 1,
            missing_models: 0,
            excluded_models: 0,
            blocking_models: 0,
          },
          risks: [],
          rows: [32_000, 128_000].map((maximum) => ({
            provider_id: "dashscope",
            provider_name: "百炼",
            model_key: "qwen3-max",
            model_name: "Qwen3 Max",
            category: "text",
            capability: "chat",
            unit_key: "input_tokens",
            unit_size: 1_000_000,
            conditions: { input_tokens_max: maximum, region: "cn-beijing" },
            rmb_cost: "2.5",
            multiplier: "1.5",
            rmb_sale_price: "3.75",
            credits: 375,
            source_type: "official_registry",
            verification_status: "verified",
            include_in_publish: true,
          })),
        }}
      />,
    );

    expect(screen.getAllByText("input_tokens")).toHaveLength(2);
    expect(screen.getByText(/"input_tokens_max":32000/)).toBeInTheDocument();
    expect(screen.getByText(/"input_tokens_max":128000/)).toBeInTheDocument();
    expect(screen.getAllByText("chat")).toHaveLength(2);
  });
});
