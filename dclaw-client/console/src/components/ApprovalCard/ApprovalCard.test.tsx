import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "./ApprovalCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

describe("ApprovalCard", () => {
  it("shows a friendly authorization reason without technical details", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn().mockResolvedValue(undefined);

    render(
      <ApprovalCard
        requestId="approval-1"
        toolName="interaction_card_create"
        severity="HIGH"
        findingsCount={2}
        findingsSummary="STRICT mode blocked this tool"
        toolParams={{ command: "rm -rf /tmp/example" }}
        createdAt={Date.now() / 1000}
        timeoutSeconds={300}
        agentId="agent-1"
        onApprove={onApprove}
        onDeny={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(
      screen.getByText("Your authorization is required"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/may read, modify, or delete local data/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/interaction_card_create/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/STRICT mode/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/rm -rf/i)).not.toBeInTheDocument();
    expect(screen.queryByText("HIGH")).not.toBeInTheDocument();
    expect(screen.queryByText("2")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /allow/i }));
    await waitFor(() => expect(onApprove).toHaveBeenCalledWith("approval-1"));
  });
});
