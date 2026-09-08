import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../../api/modules/billing";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import type { BillingReconciliationRecord } from "../../../api/types/billing";
import { ReconciliationTab, UsageTab } from "./RemoteDataTabs";

vi.mock("../../../api/modules/billing", () => ({
  billingApi: {
    listAdminUsage: vi.fn(),
    listReconciliation: vi.fn(),
    listReconciliationAudits: vi.fn(),
    resolveReconciliation: vi.fn(),
  },
}));

vi.mock("../../../api/modules/adminUsers", () => ({
  adminUsersApi: { listUsers: vi.fn() },
}));

describe("UsageTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    expect(screen.getAllByText("实扣积分")).not.toHaveLength(0);
    expect(screen.getByText("已结算")).toBeInTheDocument();
    expect(screen.queryByText(/报价/)).not.toBeInTheDocument();
    expect(screen.queryByText(/"source": "openapi"/)).not.toBeInTheDocument();
  });

  it("keeps complete fields behind a details action", async () => {
    const user = userEvent.setup();
    render(<UsageTab />);

    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("order-1")).toBeInTheDocument();
    expect(screen.getByText("admin-20260831075100")).toBeInTheDocument();
    expect(screen.getAllByText("实扣积分")).not.toHaveLength(0);
    expect(screen.queryByText("报价积分")).not.toBeInTheDocument();
  });
});

describe("ReconciliationTab", () => {
  const reconciliationItem: BillingReconciliationRecord = {
    reconciliation_id: "reconciliation-1",
    order: {
      id: "order-1",
      owner_user_id: "24",
      source: "openapi",
      expert: null,
      expert_team: null,
      status: "reconciling",
      billing_status: "reconciling",
      billing_mode: "enforced",
      is_estimate: false,
      catalog_version: "admin-20260831075100",
      quoted_credits: 23,
      captured_credits: 7,
      released_credits: 4,
      reconciling_credits: 12,
      actual_debited_credits: 7,
      call_count: 2,
      credits: { held: 12, captured: 7, released: 4, reconciling: 12 },
      tokens: { input: 1000, output: 100 },
      created_at: "2026-09-04T02:03:04+00:00",
      updated_at: "2026-09-04T02:03:05+00:00",
      publication: { id: "publication-1", name: "小顶客服" },
      application: { id: "app-1", name: "客服系统" },
    },
    item: {
      call_sequence: 2,
      expert_role: null,
      model: "deepseek-v4-flash",
      provider: "volcengine",
      capability: "chat",
      tokens: { input: 0, output: 0 },
      quoted_credits: 12,
      charged_credits: 0,
      status: "reconciling",
      catalog_version: "admin-20260831075100",
      created_at: "2026-09-04T02:03:04+00:00",
      evidence: {
        supplier_reference_present: false,
        execution_outcome: "timed_out",
      },
    },
  };

  beforeEach(() => {
    vi.mocked(adminUsersApi.listUsers).mockResolvedValue([
      { id: 24, username: "dingmai", role: "user", created_at: "" },
    ]);
    vi.mocked(billingApi.listReconciliation).mockResolvedValue({
      items: [reconciliationItem],
      next_cursor: "next-page",
    });
    vi.mocked(billingApi.listReconciliationAudits).mockResolvedValue({
      items: [],
      next_cursor: null,
    });
  });

  it("renders actionable reconciliation columns instead of raw JSON", async () => {
    render(<ReconciliationTab />);

    expect(await screen.findByText("dingmai")).toBeInTheDocument();
    expect(screen.getByText("小顶客服")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByText("volcengine")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("已扣 7")).toBeInTheDocument();
    expect(screen.getByText("已释放 4")).toBeInTheDocument();
    expect(screen.getByText("缺少供应商凭证")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "确认收费" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "确认不收费" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/"reconciliation_id"/)).not.toBeInTheDocument();
  });

  it("requires a reason and submits a non-billable decision", async () => {
    const user = userEvent.setup();
    vi.mocked(
      (
        billingApi as typeof billingApi & {
          resolveReconciliation: ReturnType<typeof vi.fn>;
        }
      ).resolveReconciliation,
    ).mockResolvedValue({ audit_id: "audit-1" });
    render(<ReconciliationTab />);

    await user.click(await screen.findByRole("button", { name: "确认不收费" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.type(screen.getByLabelText("处理依据"), "供应商后台确认未收费");
    await user.click(screen.getByRole("button", { name: "提交对账结果" }));

    expect(
      (
        billingApi as typeof billingApi & {
          resolveReconciliation: ReturnType<typeof vi.fn>;
        }
      ).resolveReconciliation,
    ).toHaveBeenCalledWith(
      "reconciliation-1",
      {
        billability: "not_billable",
        reason: "供应商后台确认未收费",
        actual_input_tokens: 0,
        actual_output_tokens: 0,
      },
      expect.any(String),
    );
  });
});
