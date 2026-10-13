import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import PricingRules from "./PricingRules";

it("submits the current revision when editing an existing rule", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(
    <PricingRules
      disabled={false}
      policies={[
        {
          id: "policy-1",
          scope_type: "provider",
          scope_key: "dashscope",
          multiplier_decimal: "1.6",
          revision: 3,
        },
      ]}
      onSave={onSave}
    />,
  );

  await user.click(screen.getByRole("button", { name: /编\s*辑/ }));
  await user.click(screen.getByRole("button", { name: "保存规则" }));

  await waitFor(() =>
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        scope_type: "provider",
        scope_key: "dashscope",
        multiplier_decimal: "1.6",
        expected_revision: 3,
      }),
    ),
  );
});

it("unpublishes an active model after confirmation", async () => {
  const onUnpublish = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(
    <PricingRules
      disabled={false}
      policies={[
        {
          id: "policy-model",
          scope_type: "model",
          scope_key: "dashscope/qwen-plus",
          multiplier_decimal: "1.5",
          revision: 6,
        },
      ]}
      catalogs={[
        {
          id: "catalog-1",
          version: "retail-v1",
          status: "published",
          effective_at: "2026-10-12T00:00:00Z",
          metadata: {},
          rules: [
            {
              id: "rule-1",
              provider_id: "dashscope",
              model_key: "qwen-plus",
              capability: "chat",
              unit_type: "tokens",
              credits_per_unit: 0,
              input_credits_per_1k: 1,
              output_credits_per_1k: 2,
              metadata: {},
            },
          ],
        },
      ]}
      onUnpublish={onUnpublish}
    />,
  );

  expect(screen.getByText("已上架")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /下\s*架/ }));
  await user.click(await screen.findByRole("button", { name: /确认\s*下架/ }));

  await waitFor(() =>
    expect(onUnpublish).toHaveBeenCalledWith("dashscope", "qwen-plus"),
  );
});
