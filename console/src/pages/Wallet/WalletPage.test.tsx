import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../api/modules/billing";
import type { BillingUsageOrder } from "../../api/types/billing";
import WalletPage from "./index";

vi.mock("../../api/modules/billing", () => ({
  billingApi: {
    getWallet: vi.fn(),
    getTopUpConfig: vi.fn(),
    listProducts: vi.fn(),
    listClaims: vi.fn(),
    listLedger: vi.fn(),
    listUsage: vi.fn(),
    getUsage: vi.fn(),
    getSummary: vi.fn(),
    submitClaim: vi.fn(),
  },
}));

const product = {
  public_id: "product-10",
  name: "CNY 10",
  description: "永久积分",
  payment_amount_fen: 1000,
  purchased_credits: 1000,
  promotional_credits: 0,
  promotional_expiry_days: null,
  status: "active" as const,
  display_order: 1,
};

describe("WalletPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(billingApi.getWallet).mockResolvedValue({
      available: 100,
      held: 5,
      purchased: 100,
      promotional: 0,
      package: 5,
    });
    vi.mocked(billingApi.getTopUpConfig).mockResolvedValue({
      enabled: true,
      qr_url: "https://example.com/pay.png",
      instructions: "扫码付款后填写付款尾号",
    });
    vi.mocked(billingApi.listProducts).mockResolvedValue({ items: [product] });
    vi.mocked(billingApi.listClaims).mockResolvedValue({ items: [] });
    vi.mocked(billingApi.listLedger).mockResolvedValue({ items: [] });
    vi.mocked(billingApi.listUsage).mockResolvedValue({ items: [] });
    vi.mocked(billingApi.getSummary).mockResolvedValue({
      window: {
        date_from: "2026-08-01",
        date_to: "2026-08-30",
        timezone: "UTC",
        lifetime: false,
      },
      totals: {
        orders: 0,
        model_calls: 0,
        input_tokens: 0,
        output_tokens: 0,
        retail_credits: 0,
        actual_debited_credits: 0,
        shadow_estimated_credits: 0,
        reconciling_credits: 0,
      },
      by_day: [],
      by_month: [],
    });
    vi.mocked(billingApi.submitClaim).mockResolvedValue({
      public_id: "claim-1",
      product_snapshot: product,
      payment_amount_fen: 1000,
      payment_channel: "wechat",
      payer_reference: "1234",
      customer_note: null,
      status: "pending",
      review_reason: null,
      reviewed_at: null,
      created_at: "2026-08-29T00:00:00Z",
      updated_at: "2026-08-29T00:00:00Z",
    });
  });

  it("renders server-owned product and submits no amount or credits", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("1,000 永久积分")).toBeInTheDocument();
    expect(screen.getByTestId("promotion-product-10")).toBeEmptyDOMElement();
    expect(
      screen.getByText("查看积分余额、购买积分并跟踪充值记录。"),
    ).toBeInTheDocument();
    expect(screen.queryByAltText("固定收款二维码")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "选择 CNY 10" }));

    const dialog = screen.getByRole("dialog", { name: "确认人工充值申请" });
    expect(screen.queryByAltText("固定收款二维码")).not.toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("扫码付款后填写付款尾号");
    expect(dialog).toHaveTextContent("CNY 10");
    expect(dialog).toHaveTextContent("¥10.00");
    expect(dialog).toHaveTextContent("1,000 永久积分");

    await user.type(screen.getByLabelText("付款尾号或凭证号"), "1234");
    await user.click(screen.getByRole("button", { name: "提交充值申请" }));

    await waitFor(() => expect(billingApi.submitClaim).toHaveBeenCalled());
    const [payload] = vi.mocked(billingApi.submitClaim).mock.calls[0];
    expect(payload).toEqual({
      product_id: "product-10",
      payment_channel: "wechat",
      payer_reference: "1234",
      customer_note: null,
    });
    expect(payload).not.toHaveProperty("credits");
    expect(payload).not.toHaveProperty("amountFen");
  });

  it("previews custom credits without allowing a frontend-only submission", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>,
    );

    await user.type(await screen.findByLabelText("自定义充值金额"), "25");

    expect(screen.getByText("预计获得 2,500 永久积分")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "自定义充值暂需后端支持" }),
    ).toBeDisabled();
  });

  it("explains that manual top-up is disabled by the platform", async () => {
    vi.mocked(billingApi.getTopUpConfig).mockResolvedValue({
      enabled: false,
      qr_url: null,
      instructions: "",
    });

    render(
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("平台尚未开启人工充值，请联系平台管理员。"),
    ).toBeInTheDocument();
  });

  it("explains that the payment QR code is missing", async () => {
    vi.mocked(billingApi.getTopUpConfig).mockResolvedValue({
      enabled: true,
      qr_url: null,
      instructions: "",
    });

    render(
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("平台尚未配置收款二维码，请联系平台管理员。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择 CNY 10" })).toBeDisabled();
  });

  it("shows mixed-source billing totals and safe per-call details", async () => {
    const usageOrder: BillingUsageOrder = {
      id: "order-public-1",
      source: "expert_team",
      expert: "research-agent",
      expert_team: "market-research-team",
      status: "reconciling",
      billing_status: "reconciling",
      billing_mode: "enforced",
      is_estimate: false,
      catalog_version: "retail-v3",
      quoted_credits: 7,
      captured_credits: 5,
      released_credits: 1,
      reconciling_credits: 1,
      credits: {
        held: 7,
        captured: 5,
        released: 1,
        reconciling: 1,
      },
      actual_debited_credits: 5,
      call_count: 1,
      tokens: { input: 1200, output: 300 },
      created_at: "2026-08-30T01:00:00Z",
      updated_at: "2026-08-30T01:01:00Z",
      items: [
        {
          call_sequence: 1,
          expert_role: "researcher",
          model: "deepseek-v4",
          provider: "deepseek",
          capability: "text",
          tokens: { input: 1200, output: 300 },
          charged_credits: 5,
          status: "reconciling",
          catalog_version: "retail-v3",
        },
      ],
    };
    vi.mocked(billingApi.listUsage).mockResolvedValue({ items: [usageOrder] });
    vi.mocked(billingApi.getUsage).mockResolvedValue(usageOrder);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("tab", { name: "模型消费" }));
    expect(screen.getByText("专家团")).toBeInTheDocument();
    expect(screen.getByText("待对账")).toBeInTheDocument();
    expect(screen.getByText("1,200 / 300")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开调用明细" }));
    expect(screen.getByText("researcher")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4 / deepseek")).toBeInTheDocument();
    expect(screen.getByText("retail-v3")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("supplier_reference");
    expect(document.body.textContent).not.toContain("item_key");
  });

  it("shows the bound publication name for OpenAPI usage", async () => {
    const usageOrder: BillingUsageOrder = {
      id: "order-openapi-1",
      source: "openapi",
      expert: null,
      expert_team: null,
      publication: { id: "publication-1", name: "国央企就业咨询老师小项" },
      status: "settled",
      billing_status: "settled",
      billing_mode: "enforced",
      is_estimate: false,
      catalog_version: "retail-v3",
      quoted_credits: 11,
      captured_credits: 11,
      released_credits: 0,
      reconciling_credits: 0,
      credits: {
        held: 0,
        captured: 11,
        released: 0,
        reconciling: 0,
      },
      actual_debited_credits: 11,
      call_count: 1,
      tokens: { input: 31_807, output: 106 },
      created_at: "2026-08-31T16:50:45Z",
      updated_at: "2026-08-31T16:50:46Z",
    };
    vi.mocked(billingApi.listUsage).mockResolvedValue({ items: [usageOrder] });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("tab", { name: "模型消费" }));
    expect(
      screen.getByText("国央企就业咨询老师小项"),
    ).toBeInTheDocument();
  });
});
