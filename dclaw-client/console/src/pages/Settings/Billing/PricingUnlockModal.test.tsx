import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { billingApi } from "../../../api/modules/billing";
import PricingUnlockModal from "./PricingUnlockModal";

vi.mock("../../../api/modules/billing", () => ({
  billingApi: { unlockPricing: vi.fn() },
}));

it("submits password once and never persists it", async () => {
  vi.mocked(billingApi.unlockPricing).mockResolvedValue({
    token: "opaque",
    expires_at: "2026-08-30T00:15:00Z",
  });
  const onUnlocked = vi.fn();
  const localSet = vi.spyOn(Storage.prototype, "setItem");
  render(
    <PricingUnlockModal
      open
      onCancel={() => undefined}
      onUnlocked={onUnlocked}
    />,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("管理员密码"), "secret");
  await user.click(screen.getByRole("button", { name: "确认解锁" }));
  await waitFor(() => expect(onUnlocked).toHaveBeenCalled());
  expect(billingApi.unlockPricing).toHaveBeenCalledWith("secret");
  expect(localSet).not.toHaveBeenCalled();
  expect(screen.getByLabelText("管理员密码")).toHaveValue("");
});
