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
  it("keeps model and date reports without the legacy token user ranking", () => {
    render(
      <DataTables
        byModelData={[
          {
            key: "provider:model",
            model: "model-a",
            prompt_tokens: 100,
            completion_tokens: 20,
            call_count: 2,
          },
        ]}
        byDateData={[
          {
            key: "2026-09-02",
            date: "2026-09-02",
            prompt_tokens: 10,
            completion_tokens: 5,
            call_count: 1,
          },
        ]}
      />,
    );

    expect(screen.getByText("model-a")).toBeInTheDocument();
    expect(screen.getByText("2026-09-02")).toBeInTheDocument();
    expect(screen.queryByText("User Ranking")).not.toBeInTheDocument();
  });
});
