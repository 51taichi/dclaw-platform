import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../api/modules/billing";
import BalanceBadge from "./BalanceBadge";

vi.mock("../../api/modules/billing", () => ({
  billingApi: { getWallet: vi.fn() },
}));

describe("BalanceBadge", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows available credits and held credits without deriving a balance", async () => {
    vi.mocked(billingApi.getWallet).mockResolvedValue({
      available: 1200,
      held: 80,
      purchased: 1000,
      promotional: 200,
      package: 80,
    });
    render(
      <MemoryRouter>
        <BalanceBadge />
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText("可用积分 1200")).toBeInTheDocument();
    expect(screen.getByText("1,200 积分")).toBeInTheDocument();
    expect(screen.getByTitle("冻结积分 80")).toBeInTheDocument();
  });

  it("shows unavailable instead of a fabricated zero and refreshes on settlement", async () => {
    vi.mocked(billingApi.getWallet)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        available: 9,
        held: 0,
        purchased: 9,
        promotional: 0,
        package: 0,
      });
    render(
      <MemoryRouter>
        <BalanceBadge />
      </MemoryRouter>,
    );
    expect(await screen.findByText("-- 积分")).toBeInTheDocument();

    window.dispatchEvent(new CustomEvent("dclaw:billing-settled"));
    await waitFor(() => expect(screen.getByText("9 积分")).toBeInTheDocument());
  });
});
