import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TokenUsagePage from "./index";

const { mockApi, mockMessage } = vi.hoisted(() => ({
  mockApi: {
    getCreditConsumptionRanking: vi.fn(),
    getTokenUsageDetails: vi.fn(),
  },
  mockMessage: { error: vi.fn() },
}));

vi.mock("../../../api", () => ({ default: mockApi }));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));
vi.mock("../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));
vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return { Card: antd.Card, Table: antd.Table };
});
vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({ current }: { current: string }) => <h1>{current}</h1>,
}));
vi.mock("./components/ModelTrendChart", () => ({
  ModelTrendChart: () => <div>model trend</div>,
}));
vi.mock("./components/TokenTypeChart", () => ({
  TokenTypeChart: () => <div>token trend</div>,
}));

describe("TokenUsagePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getCreditConsumptionRanking.mockResolvedValue({
      items: [
        {
          rank: 1,
          user_id: "2",
          username: "beta",
          consumed_credits: 12500,
          call_count: 8,
        },
      ],
      page: 1,
      page_size: 20,
      total: 1,
      period: {
        type: "month",
        anchor_date: "2026-09-02",
        started_at: "2026-08-31T16:00:00+00:00",
        ended_at: "2026-09-30T16:00:00+00:00",
        timezone: "Asia/Shanghai",
      },
    });
    mockApi.getTokenUsageDetails.mockResolvedValue([]);
  });

  it("opens on the monthly credit ranking tab without loading token reports", async () => {
    render(<TokenUsagePage />);

    expect(screen.getByRole("tab", { name: "积分消耗" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Token 消耗" })).toBeInTheDocument();
    expect(await screen.findByText("beta")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockApi.getCreditConsumptionRanking).toHaveBeenCalledWith(
        expect.objectContaining({
          period: "month",
          page: 1,
          page_size: 20,
        }),
      );
    });
    expect(mockApi.getTokenUsageDetails).not.toHaveBeenCalled();
  });
});
