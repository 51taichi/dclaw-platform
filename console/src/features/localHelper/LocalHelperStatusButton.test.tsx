import { App } from "antd";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAgentStore } from "@/stores/agentStore";

const {
  ensureLocalHelper,
  getLocalHelperStatus,
  getLocalEnvironmentStatus,
  waitForLocalHelperConnection,
  messageError,
} = vi.hoisted(() => ({
  ensureLocalHelper: vi.fn(),
  getLocalHelperStatus: vi.fn(),
  getLocalEnvironmentStatus: vi.fn(),
  waitForLocalHelperConnection: vi.fn(),
  messageError: vi.fn(),
}));

vi.mock("@/desktop/localHelper", () => ({
  ensureLocalHelper,
  getLocalHelperStatus,
  getLocalEnvironmentStatus,
  waitForLocalHelperConnection,
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: messageError, success: vi.fn() },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      _key: string,
      fallbackOrOptions?: string | { defaultValue?: string; version?: string },
    ) => {
      if (typeof fallbackOrOptions === "string") return fallbackOrOptions;
      return (fallbackOrOptions?.defaultValue ?? "").replace(
        "{{version}}",
        fallbackOrOptions?.version ?? "",
      );
    },
  }),
}));

import LocalHelperStatusButton from "./LocalHelperStatusButton";
import { LocalHelperStatusProvider } from "./LocalHelperStatusContext";
import { localAssistantMode } from "./mode";

const connected = {
  supported: true,
  installed: true,
  running: true,
  connected: true,
  paired: true,
  deviceId: "device-1",
  runnerVersion: "1.0.0",
};

function renderButton() {
  return render(
    <App>
      <LocalHelperStatusProvider>
        <LocalHelperStatusButton />
      </LocalHelperStatusProvider>
    </App>,
  );
}

describe("LocalHelperStatusButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentStore.setState({ selectedAgent: "default", agents: [] });
    getLocalHelperStatus.mockResolvedValue(connected);
    ensureLocalHelper.mockResolvedValue({ available: true, status: connected });
    waitForLocalHelperConnection.mockResolvedValue(connected);
    getLocalEnvironmentStatus.mockResolvedValue({
      state: "ready",
      reason: "none",
      protocol_version: "1",
      compatible: true,
      minimum_runner_version: "1.0.0",
      user_action: "none",
    });
  });

  it("maps signed capability declarations to the three helper modes", () => {
    expect(localAssistantMode()).toBe("none");
    expect(
      localAssistantMode({
        id: "optional",
        name: "Optional",
        description: "",
        enabled: true,
        declared_capabilities: ["local.execution.session/1"],
      }),
    ).toBe("optional");
    expect(
      localAssistantMode({
        id: "required",
        name: "Required",
        description: "",
        enabled: true,
        declared_capabilities: [
          "local.execution.session/1",
          "local.environment.preflight/1",
        ],
      }),
    ).toBe("required");
  });

  it("does not auto-check experts that do not require the helper", () => {
    renderButton();

    expect(ensureLocalHelper).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "检测本地助手" })).toBeEnabled();
  });

  it("checks and reports a connected runner when clicked", async () => {
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "检测本地助手" }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "本地助手已连接 · v1.0.0" }),
      ).toBeEnabled(),
    );
    expect(ensureLocalHelper).toHaveBeenCalledOnce();
    expect(getLocalEnvironmentStatus).toHaveBeenCalledOnce();
    expect(waitForLocalHelperConnection).not.toHaveBeenCalled();
  });

  it("auto-checks a required expert once it is selected", async () => {
    useAgentStore.setState({
      selectedAgent: "video-agent",
      agents: [
        {
          id: "video-agent",
          name: "Video Agent",
          description: "",
          enabled: true,
          declared_capabilities: [
            "local.execution.session/1",
            "local.environment.preflight/1",
          ],
        },
      ],
    });

    renderButton();

    await waitFor(() => expect(ensureLocalHelper).toHaveBeenCalledOnce());
    expect(
      await screen.findByRole("button", {
        name: "本地助手已连接 · v1.0.0",
      }),
    ).toBeEnabled();
  });

  it("does not report success when the server requires a newer Runner", async () => {
    const user = userEvent.setup();
    getLocalEnvironmentStatus.mockResolvedValue({
      state: "runner_update_required",
      reason: "runner_version_too_old",
      protocol_version: "1",
      compatible: true,
      minimum_runner_version: "1.1.0",
      user_action: "update_dclaw",
    });
    renderButton();

    await user.click(screen.getByRole("button", { name: "检测本地助手" }));

    expect(
      await screen.findByRole("button", {
        name: "本地助手需要升级",
      }),
    ).toBeEnabled();
  });

  it("distinguishes a connected but unready device from a dropped connection", async () => {
    const user = userEvent.setup();
    getLocalEnvironmentStatus.mockResolvedValue({
      state: "device_not_ready",
      reason: "device_pending",
      protocol_version: "2",
      compatible: true,
      minimum_runner_version: "1.0.0",
      user_action: "wait",
    });
    renderButton();

    await user.click(screen.getByRole("button", { name: "检测本地助手" }));

    expect(
      await screen.findByRole("button", {
        name: "本地助手已连接，但设备尚未就绪，正在自动重试。",
      }),
    ).toBeEnabled();
  });

  it("downloads an uninstalled helper when explicitly checked", async () => {
    const user = userEvent.setup();
    getLocalHelperStatus.mockResolvedValue({
      ...connected,
      installed: false,
      running: false,
      connected: false,
    });
    renderButton();

    await user.click(screen.getByRole("button", { name: "检测本地助手" }));

    expect(
      await screen.findByRole("button", {
        name: "本地助手已连接 · v1.0.0",
      }),
    ).toBeEnabled();
    expect(ensureLocalHelper).toHaveBeenCalledOnce();
  });

  it("silently retries a required helper and recovers without reopening DClaw", async () => {
    const monitorCallbacks: Array<() => void> = [];
    const originalSetInterval = window.setInterval.bind(window);
    const intervalSpy = vi
      .spyOn(window, "setInterval")
      .mockImplementation((handler, timeout, ...args) => {
        if (timeout === 15_000 && typeof handler === "function") {
          monitorCallbacks.push(handler);
        }
        return originalSetInterval(
          handler,
          timeout,
          ...args,
        ) as unknown as ReturnType<typeof setInterval>;
      });
    try {
      useAgentStore.setState({
        selectedAgent: "video-agent",
        agents: [
          {
            id: "video-agent",
            name: "Video Agent",
            description: "",
            enabled: true,
            declared_capabilities: [
              "local.execution.session/1",
              "local.environment.preflight/1",
            ],
          },
        ],
      });
      ensureLocalHelper
        .mockResolvedValueOnce({
          available: true,
          status: { ...connected, connected: false },
        })
        .mockResolvedValueOnce({ available: true, status: connected });
      waitForLocalHelperConnection.mockResolvedValueOnce({
        ...connected,
        connected: false,
      });

      const view = renderButton();
      expect(
        await screen.findByRole("button", {
          name: "本地助手连接已中断，正在自动重试。",
        }),
      ).toBeEnabled();
      expect(messageError).not.toHaveBeenCalled();

      await act(async () => {
        monitorCallbacks[monitorCallbacks.length - 1]?.();
      });
      expect(
        await screen.findByRole("button", {
          name: "本地助手已连接 · v1.0.0",
        }),
      ).toBeEnabled();
      expect(ensureLocalHelper).toHaveBeenCalledTimes(2);
      expect(messageError).not.toHaveBeenCalled();

      getLocalHelperStatus
        .mockResolvedValueOnce({ ...connected, connected: false })
        .mockResolvedValue(connected);
      await act(async () => {
        monitorCallbacks[monitorCallbacks.length - 1]?.();
      });
      await waitFor(() => expect(ensureLocalHelper).toHaveBeenCalledTimes(3));
      expect(messageError).not.toHaveBeenCalled();
      view.unmount();
    } finally {
      intervalSpy.mockRestore();
    }
  });
});
