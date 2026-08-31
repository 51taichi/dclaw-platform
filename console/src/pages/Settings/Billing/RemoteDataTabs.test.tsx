import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../../api/modules/billing";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import { UsageTab } from "./RemoteDataTabs";

vi.mock("../../../api/modules/billing", () => ({
  billingApi: { listAdminUsage: vi.fn() },
}));

vi.mock("../../../api/modules/adminUsers", () => ({
  adminUsersApi: { listUsers: vi.fn() },
}));

describe("UsageTab", () => {
  beforeEach(() => {
    vi.mocked(adminUsersApi.listUsers).mockResolvedValue([
      { id: 24, username: "dingmai", role: "user", created_at: "" },
    ]);
    vi.mocked(billingApi.listAdminUsage).mockResolvedValue({
      items: [
        {
          id: "order-1",
          owner_user_id: "24",
          source: "openapi",
          expert: null,
          expert_team: null,
          status: "settled",
          billing_status: "settled",
          billing_mode: "shadow",
          is_estimate: true,
          catalog_version: "admin-20260831075100",
          quoted_credits: 42,
          captured_credits: 21,
          released_credits: 21,
          reconciling_credits: 0,
          actual_debited_credits: 0,
          call_count: 3,
          credits: { held: 0, captured: 21, released: 21, reconciling: 0 },
          tokens: { input: 58457, output: 347 },
          created_at: "2026-08-31T11:56:51+00:00",
          updated_at: "2026-08-31T11:56:52+00:00",
        },
      ],
    });
  });

  it("renders readable usage columns instead of raw JSON", async () => {
    render(<UsageTab />);

    expect(await screen.findByText("dingmai")).toBeInTheDocument();
    expect(screen.getByText("ID 24")).toBeInTheDocument();
    expect(screen.getByText("OpenAPI")).toBeInTheDocument();
    expect(screen.getByText("输入 58,457")).toBeInTheDocument();
    expect(screen.getByText("已结算")).toBeInTheDocument();
    expect(screen.queryByText(/"source": "openapi"/)).not.toBeInTheDocument();
  });

  it("keeps complete fields behind a details action", async () => {
    const user = userEvent.setup();
    render(<UsageTab />);

    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("order-1")).toBeInTheDocument();
    expect(screen.getByText("admin-20260831075100")).toBeInTheDocument();
  });
});
