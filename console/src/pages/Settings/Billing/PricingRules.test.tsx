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
      policies={[{
        id: "policy-1",
        scope_type: "provider",
        scope_key: "dashscope",
        multiplier_decimal: "1.6",
        revision: 3,
      }]}
      onSave={onSave}
    />,
  );

  await user.click(screen.getByRole("button", { name: /编\s*辑/ }));
  await user.click(screen.getByRole("button", { name: "保存规则" }));

  await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    scope_type: "provider",
    scope_key: "dashscope",
    multiplier_decimal: "1.6",
    expected_revision: 3,
  })));
});
