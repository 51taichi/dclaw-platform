import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock, runtimeMock, authHeadersMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  runtimeMock: vi.fn(),
  authHeadersMock: vi.fn(() => ({ Authorization: "Bearer token" })),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("./runtime", () => ({ getDesktopRuntime: runtimeMock }));
vi.mock("@/api/authHeaders", () => ({ buildAuthHeaders: authHeadersMock }));
vi.mock("@/api/config", () => ({
  getApiBaseUrl: () => "https://dclaw.example",
  getApiUrl: (path: string) => `https://dclaw.example/api${path}`,
}));

import {
  ensureLocalHelper,
  getLocalEnvironmentStatus,
  toWebSocketUrl,
  waitForLocalHelperConnection,
} from "./localHelper";

describe("local helper desktop bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runtimeMock.mockResolvedValue({
      platform: "windows",
      arch: "x86_64",
      version: "2.5.3",
      brandId: "dclaw",
    });
  });

  it("converts the authenticated server path to secure WebSocket", () => {
    expect(toWebSocketUrl("/api/super-agent-support/devices/connect")).toBe(
      "wss://dclaw.example/api/super-agent-support/devices/connect",
    );
  });

  it("reuses a paired device and starts the bundled helper", async () => {
    invokeMock.mockResolvedValueOnce({
      supported: true,
      installed: true,
      running: false,
      connected: false,
      paired: true,
      deviceId: "device-1",
      runnerVersion: "1.0.0",
    });
    invokeMock.mockResolvedValueOnce({
      supported: true,
      installed: true,
      running: true,
      connected: false,
      paired: true,
      deviceId: "device-1",
      runnerVersion: "1.0.0",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            paired: true,
            device_id: "device-1",
            pairing_code: null,
            expires_in: 0,
            websocket_path: "/api/super-agent-support/devices/connect",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const result = await ensureLocalHelper();

    expect(result.available).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      "https://dclaw.example/api/super-agent-support/device-bootstrap",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ device_id: "device-1" }),
      }),
    );
    expect(invokeMock).toHaveBeenLastCalledWith("start_local_helper", {
      request: {
        serverWebsocketUri:
          "wss://dclaw.example/api/super-agent-support/devices/connect",
        pairingCode: null,
      },
    });
  });

  it("treats a server without the support plugin as unavailable", async () => {
    invokeMock.mockResolvedValueOnce({
      supported: true,
      installed: true,
      running: false,
      connected: false,
      paired: false,
      deviceId: null,
      runnerVersion: "1.0.0",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
    );

    await expect(ensureLocalHelper()).resolves.toMatchObject({
      available: false,
    });
    expect(invokeMock).toHaveBeenCalledTimes(1);
  });

  it("prompts for installation only when an on-demand check finds no helper", async () => {
    invokeMock.mockResolvedValueOnce({
      supported: true,
      installed: false,
      running: false,
      connected: false,
      paired: false,
      deviceId: null,
      runnerVersion: "1.0.0",
    });

    await expect(ensureLocalHelper()).rejects.toThrow(
      "当前设备未安装通用本地助手，请安装或升级 DClaw 客户端后重试。",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("waits until the helper reports a real server connection", async () => {
    invokeMock
      .mockResolvedValueOnce({
        supported: true,
        installed: true,
        running: true,
        connected: false,
        paired: true,
        deviceId: "device-1",
        runnerVersion: "1.0.0",
      })
      .mockResolvedValueOnce({
        supported: true,
        installed: true,
        running: true,
        connected: true,
        paired: true,
        deviceId: "device-1",
        runnerVersion: "1.0.0",
      });

    const status = await waitForLocalHelperConnection(2, 0);

    expect(status?.connected).toBe(true);
    expect(invokeMock).toHaveBeenCalledTimes(2);
  });

  it("reads the authenticated server-side Runner compatibility status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            state: "ready",
            reason: "none",
            protocol_version: "1",
            compatible: true,
            minimum_runner_version: "1.0.0",
            user_action: "none",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(getLocalEnvironmentStatus()).resolves.toMatchObject({
      state: "ready",
      minimum_runner_version: "1.0.0",
    });
    expect(fetch).toHaveBeenCalledWith(
      "https://dclaw.example/api/super-agent-support/environment-status",
      { headers: { Authorization: "Bearer token" } },
    );
  });
});
