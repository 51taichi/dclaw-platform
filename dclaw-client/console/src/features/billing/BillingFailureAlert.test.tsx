import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import BillingFailureAlert from "./BillingFailureAlert";
import { parseInsufficientCreditsFailure } from "./billingFailure";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) =>
      ({
        "billing.insufficientTitle": "积分不足，本次调用未继续",
        "billing.balanceRequired": `当前 ${values?.available}，需要 ${values?.required}`,
        "billing.topUp": "去充值",
        "billing.continueAfterTopUp": "充值后继续",
        "billing.continueFailed": "继续失败，请确认充值已到账后重试。",
      })[key] ?? key,
  }),
}));

describe("BillingFailureAlert", () => {
  it("allowlists the safe SSE billing fields", () => {
    expect(
      parseInsufficientCreditsFailure({
        type: "billing.error",
        code: "INSUFFICIENT_CREDITS",
        available_credits: 2,
        required_credits: 7,
        top_up_path: "/wallet",
        supplier_reference: "must-not-propagate",
      }),
    ).toEqual({
      code: "INSUFFICIENT_CREDITS",
      available_credits: 2,
      required_credits: 7,
      top_up_path: "/wallet",
    });
  });

  it("shows safe balance facts and links to top-up", () => {
    render(
      <MemoryRouter>
        <BillingFailureAlert
          failure={{
            code: "INSUFFICIENT_CREDITS",
            available_credits: 2,
            required_credits: 7,
            top_up_path: "/wallet",
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("积分不足，本次调用未继续")).toBeInTheDocument();
    expect(screen.getByText("当前 2，需要 7")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去充值" })).toHaveAttribute(
      "href",
      "/wallet",
    );
  });

  it("continues a paused expert team once after top-up", async () => {
    const user = userEvent.setup();
    let resolveContinue!: () => void;
    const onContinue = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveContinue = resolve;
        }),
    );
    render(
      <MemoryRouter>
        <BillingFailureAlert
          failure={{
            code: "INSUFFICIENT_CREDITS",
            available_credits: 2,
            required_credits: 7,
            top_up_path: "/wallet",
          }}
          pausedRunId="run-public-1"
          onContinue={onContinue}
        />
      </MemoryRouter>,
    );

    const button = screen.getByRole("button", { name: "充值后继续" });
    await user.dblClick(button);
    await waitFor(() => expect(onContinue).toHaveBeenCalledTimes(1));
    expect(onContinue).toHaveBeenCalledWith("run-public-1");
    await act(async () => resolveContinue());
  });

  it("keeps the retry action available after a controlled failure", async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn().mockRejectedValue(new Error("still short"));
    render(
      <MemoryRouter>
        <BillingFailureAlert
          failure={{
            code: "INSUFFICIENT_CREDITS",
            available_credits: 2,
            required_credits: 7,
            top_up_path: "/wallet",
          }}
          pausedRunId="run-public-1"
          onContinue={onContinue}
        />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "充值后继续" }));
    expect(
      await screen.findByText("继续失败，请确认充值已到账后重试。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "充值后继续" })).toBeEnabled();
  });
});
