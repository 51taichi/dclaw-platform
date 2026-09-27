import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import ConcurrencyMonitorButton, {
  type ConcurrencySnapshot,
} from "./ConcurrencyMonitorButton";

const firstSnapshot: ConcurrencySnapshot = {
  sampled_at: "2026-09-27T05:30:00+00:00",
  open_api: {
    running: 3,
    max_running: 100,
    waiting: 2,
    max_waiting_per_agent: 200,
    max_waiting_per_api_key: 100,
    wait_timeout_seconds: 60,
    by_agent: [
      {
        agent_id: "customer-service",
        running: 3,
        waiting: 2,
        max_running: 60,
      },
    ],
    by_api_key: [
      {
        api_key: "••••abcd",
        running: 3,
        waiting: 2,
        max_running: 20,
      },
    ],
  },
  platform_tasks: { running: 4, max_running: 150 },
  model_calls: { running: 2, max_running: 999, available: 997 },
};

describe("ConcurrencyMonitorButton", () => {
  it("loads a snapshot when opened and displays current and maximum values", async () => {
    const loadSnapshot = vi.fn().mockResolvedValue(firstSnapshot);
    const user = userEvent.setup();
    renderWithProviders(
      <ConcurrencyMonitorButton loadSnapshot={loadSnapshot} />,
    );

    await user.click(screen.getByRole("button", { name: "并发监控" }));

    expect(await screen.findByText("3 / 100")).toBeInTheDocument();
    expect(screen.getByText("4 / 150")).toBeInTheDocument();
    expect(screen.getByText("2 / 999")).toBeInTheDocument();
    expect(screen.getByText("当前排队 2")).toBeInTheDocument();
    expect(screen.getByText("customer-service")).toBeInTheDocument();
    expect(screen.getByText("••••abcd")).toBeInTheDocument();
    expect(loadSnapshot).toHaveBeenCalledTimes(1);
  });

  it("reloads the current values when refresh is clicked", async () => {
    const loadSnapshot = vi
      .fn()
      .mockResolvedValueOnce(firstSnapshot)
      .mockResolvedValueOnce({
        ...firstSnapshot,
        open_api: { ...firstSnapshot.open_api, running: 7, waiting: 0 },
      });
    const user = userEvent.setup();
    renderWithProviders(
      <ConcurrencyMonitorButton loadSnapshot={loadSnapshot} />,
    );

    await user.click(screen.getByRole("button", { name: "并发监控" }));
    expect(await screen.findByText("3 / 100")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "刷新" }));

    await waitFor(() =>
      expect(screen.getByText("7 / 100")).toBeInTheDocument(),
    );
    expect(screen.getByText("当前排队 0")).toBeInTheDocument();
    expect(loadSnapshot).toHaveBeenCalledTimes(2);
  });
});
