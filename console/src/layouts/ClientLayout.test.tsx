import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ClientLayout from "./ClientLayout";

const authState = vi.hoisted(() => ({
  role: null as string | null,
  scenes: [] as Array<{
    key: string;
    title: string;
    url: string;
    icon?: string;
  }>,
}));
const tauriInvoke = vi.hoisted(() => vi.fn(() => Promise.resolve()));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauriInvoke }));

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: {
    getConversationRoute: vi.fn(async (id: string) => ({
      conversation_id: id,
      agent_id: "default",
    })),
  },
}));

vi.mock("./Header", () => ({
  default: ({
    scenes = [],
    activeSceneKey,
    onSceneChange,
  }: {
    scenes?: Array<{ key: string; title: string }>;
    activeSceneKey?: string;
    onSceneChange?: (key: string) => void;
  }) => (
    <div data-active-scene={activeSceneKey} data-testid="header">
      <button onClick={() => onSceneChange?.("workbench")}>工作台</button>
      {scenes.map((scene) => (
        <button key={scene.key} onClick={() => onSceneChange?.(scene.key)}>
          {scene.title}
        </button>
      ))}
    </div>
  ),
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

vi.mock("../api/modules/billing", () => ({
  billingApi: {
    getCreditAlerts: vi.fn(async () => ({
      preferences: { warning_threshold: 5000, critical_threshold: 1000 },
      available: 4500,
      alert: {
        tier: "warning",
        threshold: 5000,
        available: 4500,
        triggered_at: "2026-09-29T00:00:00Z",
      },
    })),
    dismissCreditAlert: vi.fn(),
  },
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
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = null;
    authState.scenes = [];
    delete (window as Window & { __TAURI_INTERNALS__?: unknown })
      .__TAURI_INTERNALS__;
  });

  it("mounts the persistent alert above routed content", async () => {
    renderAt("/workbench");
    const banner = await screen.findByText("积分不足提醒");
    const content = await screen.findByTestId("workbench-page");
    expect(
      banner.compareDocumentPosition(content) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
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

  it("hosts configured scenes separately without replacing workbench routing", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ =
      {};
    const bounds = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 8,
        y: 64,
        top: 64,
        left: 8,
        right: 1008,
        bottom: 764,
        width: 1000,
        height: 700,
        toJSON: () => ({}),
      });
    authState.scenes = [
      {
        key: "customer-service",
        title: "AI客服",
        url: "https://service.example.com/console",
      },
    ];

    renderAt("/workbench");
    fireEvent.click(await screen.findByRole("button", { name: "AI客服" }));

    expect(await screen.findByTestId("header")).toHaveAttribute(
      "data-active-scene",
      "customer-service",
    );
    expect(
      document.querySelector('[data-scene-webview="customer-service"]'),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(tauriInvoke).toHaveBeenCalledWith("show_scene_webview", {
        sceneKey: "customer-service",
        url: "https://service.example.com/console",
        bounds: { x: 9, y: 65, width: 998, height: 698 },
      }),
    );
    expect(document.querySelector("iframe")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workbench-page")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "工作台" }));
    expect(screen.getByTestId("header")).toHaveAttribute(
      "data-active-scene",
      "workbench",
    );
    expect(await screen.findByTestId("workbench-page")).toBeInTheDocument();
    await waitFor(() =>
      expect(tauriInvoke).toHaveBeenCalledWith("hide_scene_webviews"),
    );
    bounds.mockRestore();
  });
});
