import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalDialog, type ApprovalDialogRequest } from "./ApprovalDialog";

vi.mock("./ApprovalCard", () => ({
  ApprovalCard: ({ requestId }: { requestId: string }) => (
    <div data-testid="approval-card">{requestId}</div>
  ),
}));

function makeRequest(
  requestId: string,
  createdAt: number,
): ApprovalDialogRequest {
  return {
    requestId,
    createdAt,
    toolName: "execute_shell_command",
    severity: "HIGH",
    findingsCount: 1,
    findingsSummary: "Dangerous command",
    toolParams: { command: "echo test" },
    timeoutSeconds: 300,
    agentId: "agent-1",
  };
}

describe("ApprovalDialog", () => {
  it("shows only the oldest approval when multiple requests are pending", () => {
    const requests = new Map([
      ["newer", makeRequest("newer", 20)],
      ["oldest", makeRequest("oldest", 10)],
    ]);

    render(
      <ApprovalDialog
        requests={requests}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getAllByTestId("approval-card")).toHaveLength(1);
    expect(screen.getByTestId("approval-card")).toHaveTextContent("oldest");
  });

  it("closes automatically when polling removes the approval", async () => {
    const view = render(
      <ApprovalDialog
        requests={new Map([["approval-1", makeRequest("approval-1", 10)]])}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByTestId("approval-card")).toBeInTheDocument();

    view.rerender(
      <ApprovalDialog
        requests={new Map()}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("approval-card")).not.toBeInTheDocument();
    });
  });
});
