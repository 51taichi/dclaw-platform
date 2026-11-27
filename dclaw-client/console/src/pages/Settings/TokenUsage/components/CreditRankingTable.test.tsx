import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CreditRankingTable } from "./CreditRankingTable";

vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return { Card: antd.Card, Table: antd.Table };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

describe("CreditRankingTable", () => {
  it("shows customer credit consumption in server ranking order", () => {
    render(
      <CreditRankingTable
        items={[
          {
            rank: 1,
            user_id: "2",
            username: "beta",
            consumed_credits: 12500,
            call_count: 8,
          },
          {
            rank: 2,
            user_id: "1",
            username: "alpha",
            consumed_credits: 40,
            call_count: 2,
          },
        ]}
        loading={false}
        page={1}
        pageSize={20}
        total={2}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByText("客户积分消耗排行")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.getByText("ID 2")).toBeInTheDocument();
    expect(screen.getByText("12,500")).toBeInTheDocument();
    expect(screen.getByText("实际消耗积分")).toBeInTheDocument();
    expect(screen.getByText("调用次数")).toBeInTheDocument();
  });
});
