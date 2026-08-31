import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DataTables } from "./DataTables";

vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return { Card: antd.Card, Table: antd.Table };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

describe("DataTables", () => {
  it("shows account names with user IDs and preserves system usage", () => {
    render(
      <DataTables
        byModelData={[]}
        byDateData={[]}
        byUserData={[
          {
            key: "24",
            user_id: "24",
            prompt_tokens: 100,
            completion_tokens: 20,
            call_count: 2,
          },
          {
            key: "System",
            user_id: "System",
            prompt_tokens: 10,
            completion_tokens: 5,
            call_count: 1,
          },
        ]}
        userNames={{ "24": "dingmai" }}
      />,
    );

    expect(screen.getByText("dingmai")).toBeInTheDocument();
    expect(screen.getByText("ID 24")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
  });
});
