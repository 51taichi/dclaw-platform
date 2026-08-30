import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../../api/modules/billing";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import BillingSettings from "./index";

vi.mock("../../../api/modules/billing", () => ({
  billingApi: {
    listAdminClaims: vi.fn(),
    listAdminProducts: vi.fn(),
    approveClaim: vi.fn(),
    rejectClaim: vi.fn(),
  },
}));

vi.mock("../../../api/modules/adminUsers", () => ({
  adminUsersApi: {
    listUsers: vi.fn(),
  },
}));

const product = {
  public_id: "product-1",
  name: "CNY 10",
  description: null,
  payment_amount_fen: 1000,
  purchased_credits: 1000,
  promotional_credits: 0,
  promotional_expiry_days: null,
  status: "active" as const,
  display_order: 1,
};

describe("BillingSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminUsersApi.listUsers).mockResolvedValue([
      {
        id: 24,
        username: "dingmai",
        role: "user",
        created_at: "2026-08-28T12:53:23Z",
      },
    ]);
    vi.mocked(billingApi.listAdminClaims).mockResolvedValue({
      items: [
        {
          public_id: "claim-1",
          product_snapshot: product,
          payment_amount_fen: 1000,
          payment_channel: "wechat",
          payer_reference: "tail-1234",
          customer_note: null,
          status: "pending",
          review_reason: null,
          reviewed_at: null,
          created_at: "2026-08-29T00:00:00Z",
          updated_at: "2026-08-29T00:00:00Z",
          owner_id: "24",
        },
      ],
    });
    vi.mocked(billingApi.listAdminProducts).mockResolvedValue({
      items: [product],
    });
    vi.mocked(billingApi.approveClaim).mockResolvedValue({
      ...awaitedClaim(),
      status: "approved",
    });
  });

  it("approves a stored claim with a required reason and no balance editor", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <BillingSettings />
      </MemoryRouter>,
    );
    expect(screen.getByText("设置")).toBeInTheDocument();
    expect(screen.getByText("积分与计费")).toBeInTheDocument();
    expect(await screen.findByText("tail-1234")).toBeInTheDocument();
    expect(screen.getByText("dingmai")).toBeInTheDocument();
    expect(screen.getByText("ID 24")).toBeInTheDocument();
    expect(screen.queryByLabelText(/直接修改余额/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("spinbutton", { name: /赠送积分/ }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "批准" }));
    const confirm = screen.getByRole("button", { name: "确认批准" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("审核原因"), "receipt verified");
    await user.click(confirm);
    await waitFor(() => expect(billingApi.approveClaim).toHaveBeenCalled());
    expect(vi.mocked(billingApi.approveClaim).mock.calls[0][0]).toBe("claim-1");
    expect(vi.mocked(billingApi.approveClaim).mock.calls[0][1]).toBe(
      "receipt verified",
    );
  });
});

function awaitedClaim() {
  return {
    public_id: "claim-1",
    product_snapshot: product,
    payment_amount_fen: 1000,
    payment_channel: "wechat" as const,
    payer_reference: "tail-1234",
    customer_note: null,
    review_reason: null,
    reviewed_at: null,
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
    owner_id: "user-1",
  };
}
