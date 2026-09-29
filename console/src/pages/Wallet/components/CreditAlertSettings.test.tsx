import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingApi } from "../../../api/modules/billing";
import CreditAlertSettings from "./CreditAlertSettings";

vi.mock("../../../api/modules/billing", () => ({
  billingApi: {
    getCreditAlerts: vi.fn(),
    updateCreditAlertPreferences: vi.fn(),
  },
}));

const resource = {
  preferences: { warning_threshold: 5000, critical_threshold: 1000 },
  available: 8000,
  alert: null,
};

describe("CreditAlertSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(billingApi.getCreditAlerts).mockResolvedValue(resource);
    vi.mocked(billingApi.updateCreditAlertPreferences).mockResolvedValue(resource);
  });

  it("loads defaults and saves literal integer thresholds", async () => {
    const user = userEvent.setup();
    const dispatch = vi.spyOn(window, "dispatchEvent");
    render(<CreditAlertSettings />);
    const warning = await screen.findByLabelText("预警积分");
    const critical = screen.getByLabelText("严重预警积分");
    expect(warning).toHaveValue("5000");
    expect(critical).toHaveValue("1000");
    fireEvent.change(warning, { target: { value: "6000" } });
    fireEvent.change(critical, { target: { value: "1200" } });
    await user.click(screen.getByRole("button", { name: "保存预警设置" }));
    await waitFor(() => expect(billingApi.updateCreditAlertPreferences).toHaveBeenCalledWith({
      warning_threshold: 6000, critical_threshold: 1200,
    }));
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: "dclaw:credit-alert-changed" }));
  });

  it.each([
    [1000, 1000], [999, 1000], [5000, -1],
  ])("blocks invalid ordering %s/%s", async (warningValue, criticalValue) => {
    const user = userEvent.setup();
    render(<CreditAlertSettings />);
    const warning = await screen.findByLabelText("预警积分");
    const critical = screen.getByLabelText("严重预警积分");
    fireEvent.change(warning, { target: { value: String(warningValue) } });
    fireEvent.change(critical, { target: { value: String(criticalValue) } });
    await user.click(screen.getByRole("button", { name: "保存预警设置" }));
    expect(await screen.findByText("严重预警积分必须大于等于 0，且小于预警积分")).toBeInTheDocument();
    expect(billingApi.updateCreditAlertPreferences).not.toHaveBeenCalled();
  });

  it("keeps the form usable and emits no event after a server error", async () => {
    const user = userEvent.setup();
    const dispatch = vi.spyOn(window, "dispatchEvent");
    vi.mocked(billingApi.updateCreditAlertPreferences).mockRejectedValue(new Error("save failed"));
    render(<CreditAlertSettings />);
    const warning = await screen.findByLabelText("预警积分");
    fireEvent.change(warning, { target: { value: "6000" } });
    await user.click(screen.getByRole("button", { name: "保存预警设置" }));
    expect(await screen.findByText("save failed")).toBeInTheDocument();
    expect(warning).toHaveValue("6000");
    expect(dispatch).not.toHaveBeenCalledWith(expect.objectContaining({ type: "dclaw:credit-alert-changed" }));
  });
});
