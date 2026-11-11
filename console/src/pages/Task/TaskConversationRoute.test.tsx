import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { useAgentStore } from "../../stores/agentStore";
import { buildAuthHeaders } from "../../api/authHeaders";
import TaskConversationRoute from "./TaskConversationRoute";
import sessionApi from "../Chat/sessionApi";

const { resolveRoute } = vi.hoisted(() => ({ resolveRoute: vi.fn() }));
vi.mock("../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: { getConversationRoute: resolveRoute },
}));

let mountedAgents: Array<string | undefined>;
function ChatConsumer() {
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  useEffect(() => {
    mountedAgents.push(buildAuthHeaders()["X-Agent-Id"]);
  }, []);
  return <div>会话所属专家：{selectedAgent}</div>;
}
function SwitchRoute() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/task/second")}>切换任务</button>;
}
function show(path = "/task/first") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SwitchRoute />
      <TaskConversationRoute>
        <ChatConsumer />
      </TaskConversationRoute>
    </MemoryRouter>,
  );
}

describe("TaskConversationRoute", () => {
  beforeEach(() => {
    resolveRoute.mockReset();
    mountedAgents = [];
    useAgentStore.getState().setSelectedAgent("default");
    useAgentStore.getState().setActiveMode("craft");
  });
  it("waits for trusted ownership before mounting chat under a persisted agent scope", async () => {
    let finish!: (route: { conversation_id: string; agent_id: string }) => void;
    resolveRoute.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    show();
    expect(screen.queryByText(/会话所属专家/)).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("正在恢复会话");
    await act(async () => {
      finish({ conversation_id: "first", agent_id: "luyu" });
    });
    expect(await screen.findByText("会话所属专家：luyu")).toBeInTheDocument();
    expect(mountedAgents).toEqual(["luyu"]);
    expect(useAgentStore.getState().activeMode).toBe("");
  });
  it("does not mount or redirect a missing/inaccessible conversation and supports retry", async () => {
    resolveRoute.mockRejectedValueOnce(new Error("not accessible"));
    show();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(mountedAgents).toEqual([]);
    resolveRoute.mockResolvedValue({
      conversation_id: "first",
      agent_id: "luyu",
    });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("会话所属专家：luyu")).toBeInTheDocument();
  });
  it("ignores delayed ownership from a previous route", async () => {
    let finish!: (route: { conversation_id: string; agent_id: string }) => void;
    resolveRoute
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      )
      .mockResolvedValue({
        conversation_id: "second",
        agent_id: "second-expert",
      });
    show();
    fireEvent.click(screen.getByRole("button", { name: "切换任务" }));
    expect(
      await screen.findByText("会话所属专家：second-expert"),
    ).toBeInTheDocument();
    await act(async () => {
      finish({ conversation_id: "first", agent_id: "luyu" });
    });
    expect(useAgentStore.getState().selectedAgent).toBe("second-expert");
    expect(mountedAgents).toEqual(["second-expert"]);
  });
  it("does not resolve new draft tasks or change their selected expert", () => {
    show("/task");
    expect(screen.getByText("会话所属专家：default")).toBeInTheDocument();
    expect(resolveRoute).not.toHaveBeenCalled();
    expect(useAgentStore.getState().activeMode).toBe("craft");
  });

  it("preserves the mounted draft runtime when its first message acquires a task ID", async () => {
    resolveRoute.mockReturnValue(new Promise(() => {}));
    show("/task");
    fireEvent.click(screen.getByRole("button", { name: "切换任务" }));
    expect(screen.getByText("会话所属专家：default")).toBeInTheDocument();
    expect(mountedAgents).toEqual(["default"]);
    expect(resolveRoute).not.toHaveBeenCalled();
  });

  it("clears the previous agent session cache before opening the resolved owner", async () => {
    sessionApi.resolveSubmittedSession("old-chat", "old-real-id");
    expect(sessionApi.getRealIdForSession("old-chat")).toBe("old-real-id");
    resolveRoute.mockResolvedValue({
      conversation_id: "first",
      agent_id: "luyu",
    });
    show();
    await screen.findByText("会话所属专家：luyu");
    expect(sessionApi.getRealIdForSession("old-chat")).toBeNull();
  });
  it("rejects a route response bound to a different conversation", async () => {
    resolveRoute.mockResolvedValue({
      conversation_id: "other",
      agent_id: "luyu",
    });
    show();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(mountedAgents).toEqual([]);
  });
});
