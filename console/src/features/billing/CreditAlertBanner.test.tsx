import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../api/modules/billing";
import type { CreditAlertResource } from "../../api/types/billing";
import CreditAlertBanner from "./CreditAlertBanner";

vi.mock("../../api/modules/billing", () => ({
  billingApi: { getCreditAlerts: vi.fn(), dismissCreditAlert: vi.fn() },
}));

const warning: CreditAlertResource = {
  preferences: { warning_threshold: 5000, critical_threshold: 1000 },
  available: 4500,
  alert: { tier: "warning", threshold: 5000, available: 4500, triggered_at: "2026-09-29T00:00:00Z" },
};
const critical: CreditAlertResource = {
  ...warning,
  available: 900,
  alert: { tier: "critical", threshold: 1000, available: 900, triggered_at: "2026-09-29T00:01:00Z" },
};
const clear: CreditAlertResource = { ...warning, alert: null };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function Location() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

function renderBanner() {
  return render(
    <MemoryRouter initialEntries={["/workbench"]}>
      <CreditAlertBanner />
      <Location />
      <Routes><Route path="*" element={<div>page</div>} /></Routes>
    </MemoryRouter>,
  );
}

describe("CreditAlertBanner", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("shows no fabricated balance for null or failed resources", async () => {
    vi.mocked(billingApi.getCreditAlerts).mockResolvedValue(clear);
    const view = renderBanner();
    await waitFor(() => expect(billingApi.getCreditAlerts).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    vi.mocked(billingApi.getCreditAlerts).mockRejectedValue(new Error("offline"));
    window.dispatchEvent(new CustomEvent("dclaw:credit-alert-changed"));
    await waitFor(() => expect(billingApi.getCreditAlerts).toHaveBeenCalledTimes(2));
    expect(document.body).not.toHaveTextContent("0 积分");
    view.unmount();
  });

  it.each([[warning, "积分不足提醒"], [critical, "积分严重不足"]])(
    "renders the server tier and navigates to wallet",
    async (resource, title) => {
      const user = userEvent.setup();
      vi.mocked(billingApi.getCreditAlerts).mockResolvedValue(resource);
      renderBanner();
      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(resource.available.toLocaleString()))).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "去充值" }));
      expect(screen.getByTestId("location")).toHaveTextContent("/wallet");
      expect(screen.getByText(title)).toBeInTheDocument();
    },
  );

  it("dismisses only after success and then refetches", async () => {
    const user = userEvent.setup();
    vi.mocked(billingApi.getCreditAlerts).mockResolvedValueOnce(warning).mockResolvedValueOnce(clear);
    vi.mocked(billingApi.dismissCreditAlert).mockRejectedValueOnce(new Error("failed"));
    renderBanner();
    await screen.findByText("积分不足提醒");
    await user.click(screen.getByRole("button", { name: "不再提醒" }));
    expect(screen.getByText("积分不足提醒")).toBeInTheDocument();
    await waitFor(() => expect(billingApi.dismissCreditAlert).toHaveBeenCalledTimes(1));
    vi.mocked(billingApi.dismissCreditAlert).mockResolvedValue(clear);
    await user.click(screen.getByRole("button", { name: /不再提醒/ }));
    await waitFor(() => expect(screen.queryByText("积分不足提醒")).not.toBeInTheDocument());
    expect(billingApi.dismissCreditAlert).toHaveBeenLastCalledWith("warning");
  });

  it("refreshes for both events and every 60 seconds", async () => {
    vi.useFakeTimers();
    vi.mocked(billingApi.getCreditAlerts).mockResolvedValue(clear);
    renderBanner();
    await act(async () => Promise.resolve());
    window.dispatchEvent(new CustomEvent("dclaw:billing-settled"));
    window.dispatchEvent(new CustomEvent("dclaw:credit-alert-changed"));
    await act(async () => { vi.advanceTimersByTime(60_000); await Promise.resolve(); });
    expect(billingApi.getCreditAlerts).toHaveBeenCalledTimes(4);
  });

  it("ignores refresh responses that resolve out of order", async () => {
    const oldRequest = deferred<CreditAlertResource>();
    const newRequest = deferred<CreditAlertResource>();
    vi.mocked(billingApi.getCreditAlerts)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);
    renderBanner();
    window.dispatchEvent(new CustomEvent("dclaw:billing-settled"));
    await waitFor(() => expect(billingApi.getCreditAlerts).toHaveBeenCalledTimes(2));

    newRequest.resolve(critical);
    expect(await screen.findByText("积分严重不足")).toBeInTheDocument();
    oldRequest.resolve(warning);
    await act(async () => Promise.resolve());

    expect(screen.getByText("积分严重不足")).toBeInTheDocument();
    expect(screen.queryByText("积分不足提醒")).not.toBeInTheDocument();
  });

  it("does not restore an alert from a refresh started before dismissal", async () => {
    const staleRequest = deferred<CreditAlertResource>();
    vi.mocked(billingApi.getCreditAlerts)
      .mockResolvedValueOnce(warning)
      .mockReturnValueOnce(staleRequest.promise)
      .mockResolvedValue(clear);
    vi.mocked(billingApi.dismissCreditAlert).mockResolvedValue(clear);
    const user = userEvent.setup();
    renderBanner();
    await screen.findByText("积分不足提醒");
    window.dispatchEvent(new CustomEvent("dclaw:billing-settled"));
    await waitFor(() => expect(billingApi.getCreditAlerts).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole("button", { name: "不再提醒" }));
    await waitFor(() => expect(screen.queryByText("积分不足提醒")).not.toBeInTheDocument());
    staleRequest.resolve(warning);
    await act(async () => Promise.resolve());

    expect(screen.queryByText("积分不足提醒")).not.toBeInTheDocument();
  });
});
