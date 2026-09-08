import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ClientLayout from "./ClientLayout";

vi.mock("../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: {
    getConversationRoute: vi.fn(async (id: string) => ({
      conversation_id: id,
      agent_id: "default",
    })),
  },
}));

vi.mock("./Header", () => ({
  default: () => <div data-testid="header" />,
}));

vi.mock("./Sidebar", () => ({
  default: ({ selectedKey }: { selectedKey: string }) => (
    <div data-testid="sidebar" data-selected-key={selectedKey} />
  ),
}));

vi.mock("../components/ConsolePollService", () => ({
  default: () => null,
}));

vi.mock("../plugins/PluginContext", () => ({
  usePlugins: () => ({ pluginRoutes: [] }),
}));

vi.mock("../pages/Chat", () => ({
  default: () => <div data-testid="legacy-chat-page">Legacy Chat</div>,
}));

vi.mock("../pages/Claw", () => ({
  default: () => <div data-testid="claw-page">Claw</div>,
}));

vi.mock("../pages/Workbench", () => ({
  default: () => <div data-testid="workbench-page">Workbench</div>,
}));

vi.mock("../pages/Task", async () => {
  const { useState } = await import("react");
  const { useNavigate } = await import("react-router-dom");
  return {
    default: function TaskRuntimeBoundary() {
      const [sending, setSending] = useState(false);
      const navigate = useNavigate();
      return (
        <div data-testid="task-page">
          Task
          <button
            onClick={() => {
              setSending(true);
              navigate("/task/created-id");
            }}
          >
            发送首条消息
          </button>
          {sending && <span>首条消息发送中</span>}
        </div>
      );
    },
  };
});

vi.mock("../pages/AigcStudio", () => ({
  default: () => <div data-testid="aigc-studio-page">AIGC Studio</div>,
}));

vi.mock("../pages/Wallet", () => ({
  default: () => <div data-testid="wallet-page">Wallet</div>,
}));

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <ClientLayout />
    </MemoryRouter>,
  );
}

describe("ClientLayout routing", () => {
  it("retains the active runtime while a draft becomes a persisted task", async () => {
    renderAt("/task");
    fireEvent.click(
      await screen.findByRole("button", { name: "发送首条消息" }),
    );
    expect(await screen.findByText("首条消息发送中")).toBeInTheDocument();
  });
  it("redirects the retired /chat route to workbench instead of rendering the old chat page", async () => {
    renderAt("/chat");

    expect(await screen.findByTestId("workbench-page")).toBeInTheDocument();
    expect(screen.queryByTestId("legacy-chat-page")).not.toBeInTheDocument();
  });

  it("keeps task and claw routes available", async () => {
    const taskView = renderAt("/task/task-id");
    expect(await screen.findByTestId("task-page")).toBeInTheDocument();
    taskView.unmount();

    renderAt("/claw/claw-id");
    expect(await screen.findByTestId("claw-page")).toBeInTheDocument();
  });

  it("exposes the customer wallet route", async () => {
    renderAt("/wallet");
    expect(await screen.findByTestId("wallet-page")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toHaveAttribute(
      "data-selected-key",
      "wallet",
    );
  });
});
