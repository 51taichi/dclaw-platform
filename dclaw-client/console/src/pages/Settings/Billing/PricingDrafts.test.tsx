import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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

  it("lets the administrator change a model publication decision", async () => {
    const onModelDecision = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <PricingDrafts
        catalogs={[]}
        canMutate
        onModelDecision={onModelDecision}
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
          rows: [
            {
              provider_id: "dashscope",
              provider_name: "百炼",
              model_key: "qwen-plus",
              model_name: "Qwen Plus",
              category: "text",
              capability: "chat",
              unit_key: "input_tokens",
              unit_size: 1_000_000,
              conditions: {},
              rmb_cost: "2.5",
              multiplier: "1.5",
              rmb_sale_price: "3.75",
              credits: 375,
              source_type: "official_registry",
              verification_status: "verified",
              evidence_level: "official_verified",
              include_in_publish: true,
            },
          ],
        }}
      />,
    );

    const publicationSwitch = screen.getByRole("switch", {
      name: "Qwen Plus 本次发布",
    });
    expect(publicationSwitch).toBeChecked();
    await user.click(publicationSwitch);
    await user.type(screen.getByLabelText("发布决策原因"), "本次暂缓");
    await user.click(screen.getByText("保存发布状态"));

    expect(onModelDecision).toHaveBeenCalledWith(
      "dashscope",
      "qwen-plus",
      false,
      "本次暂缓",
    );
  });
});
