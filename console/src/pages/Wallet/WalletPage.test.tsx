import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../api/modules/billing";
import WalletPage from "./index";

vi.mock("../../api/modules/billing", () => ({
  billingApi: {
    getWallet: vi.fn(),
    getTopUpConfig: vi.fn(),
    listProducts: vi.fn(),
    listClaims: vi.fn(),
    listLedger: vi.fn(),
    listUsage: vi.fn(),
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
    expect(screen.getByAltText("固定收款二维码")).toHaveAttribute(
      "src",
      "https://example.com/pay.png",
    );

    await user.click(screen.getByRole("button", { name: "选择 CNY 10" }));
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
});
