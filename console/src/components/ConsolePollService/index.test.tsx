import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consoleApi, type PendingApproval } from "../../api/modules/console";
import { type RuntimeEvent } from "../../api/modules/runtimeEvents";
import {
  ApprovalProvider,
  useApprovalContext,
} from "../../contexts/ApprovalContext";
import { useRuntimeEvents } from "../../contexts/RuntimeEventContext";
import ConsolePollService from "./index";

vi.mock("../../api/modules/console", () => ({
  consoleApi: {
    getPushMessages: vi.fn(),
  },
}));

vi.mock("../../contexts/RuntimeEventContext", () => ({
  useRuntimeEvents: vi.fn(),
}));

let activeSessionId: string | null = "session-1";
let runtimeEvents: RuntimeEvent[] = [];

function mockRuntimeEvents() {
  vi.mocked(useRuntimeEvents).mockImplementation(() => ({
    activeSessionId,
    setActiveSessionId: vi.fn(),
    connected: true,
    fallbackPolling: false,
    lastEventId: runtimeEvents[runtimeEvents.length - 1]?.id ?? null,
    events: runtimeEvents,
    clearEvents: vi.fn(),
  }));
}

function ApprovalProbe() {
  const { approvals } = useApprovalContext();
  return <span data-testid="approval-count">{approvals.length}</span>;
}

function renderService() {
  return render(
    <ApprovalProvider>
      <ConsolePollService />
      <ApprovalProbe />
    </ApprovalProvider>,
  );
}

function makeApproval(
  overrides: Partial<PendingApproval> = {},
): PendingApproval {
  return {
    request_id: "approval-1",
    session_id: "session-1",
    root_session_id: "session-1",
    agent_id: "agent-1",
    tool_name: "execute_shell_command",
    severity: "HIGH",
    findings_count: 1,
    findings_summary: "Dangerous command",
    tool_params: {},
    created_at: 1,
    timeout_seconds: 300,
    ...overrides,
  };
}

describe("ConsolePollService runtime events", () => {
  beforeEach(() => {
    activeSessionId = "session-1";
    runtimeEvents = [];
    mockRuntimeEvents();
    vi.mocked(consoleApi.getPushMessages).mockResolvedValue({
      messages: [],
      pending_approvals: [],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("refreshes session-scoped push messages when a runtime event arrives", async () => {
    vi.mocked(consoleApi.getPushMessages)
      .mockResolvedValueOnce({ messages: [], pending_approvals: [] })
      .mockResolvedValueOnce({
        messages: [{ id: "message-1", text: "技能导入完成" }],
        pending_approvals: [],
      });

    const view = renderService();

    await waitFor(() => {
      expect(consoleApi.getPushMessages).toHaveBeenCalledWith();
    });

    runtimeEvents = [
      {
        id: "event-1",
        type: "task.progress",
        scope: "task",
        session_id: "session-1",
        message: "后台状态更新",
        created_at: 1,
      },
    ];
    view.rerender(
      <ApprovalProvider>
        <ConsolePollService />
        <ApprovalProbe />
      </ApprovalProvider>,
    );

    await waitFor(() => {
      expect(consoleApi.getPushMessages).toHaveBeenCalledWith("session-1");
    });
    expect(await screen.findByText("技能导入完成")).toBeInTheDocument();
  });

  it("updates pending approvals from the active session after approval events", async () => {
    vi.mocked(consoleApi.getPushMessages)
      .mockResolvedValueOnce({ messages: [], pending_approvals: [] })
      .mockResolvedValueOnce({
        messages: [],
        pending_approvals: [makeApproval()],
      });

    const view = renderService();

    await waitFor(() => {
      expect(consoleApi.getPushMessages).toHaveBeenCalledWith();
    });

    runtimeEvents = [
      {
        id: "event-approval-1",
        type: "approval.created",
        scope: "approval",
        session_id: "session-1",
        status: "pending",
        created_at: 1,
      },
    ];
    view.rerender(
      <ApprovalProvider>
        <ConsolePollService />
        <ApprovalProbe />
      </ApprovalProvider>,
    );

    await waitFor(() => {
      expect(consoleApi.getPushMessages).toHaveBeenCalledWith("session-1");
    });
    await waitFor(() => {
      expect(screen.getByTestId("approval-count")).toHaveTextContent("1");
    });
  });

  it("refreshes the active session after terminal task events", async () => {
    vi.mocked(consoleApi.getPushMessages)
      .mockResolvedValueOnce({ messages: [], pending_approvals: [] })
      .mockResolvedValueOnce({
        messages: [{ id: "message-done", text: "任务已完成" }],
        pending_approvals: [],
      });

    const view = renderService();

    await waitFor(() => {
      expect(consoleApi.getPushMessages).toHaveBeenCalledWith();
    });

    runtimeEvents = [
      {
        id: "event-task-done",
        type: "task.completed",
        scope: "task",
        session_id: "session-1",
        status: "completed",
        created_at: 1,
      },
    ];
    view.rerender(
      <ApprovalProvider>
        <ConsolePollService />
        <ApprovalProbe />
      </ApprovalProvider>,
    );

    await waitFor(() => {
      expect(consoleApi.getPushMessages).toHaveBeenCalledWith("session-1");
    });
    expect(await screen.findByText("任务已完成")).toBeInTheDocument();
  });
});
