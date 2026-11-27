import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PluginProvider, usePlugins } from "./PluginContext";

const { authState, mockLoadAllPlugins } = vi.hoisted(() => ({
  authState: {
    role: "user" as string | null,
    status: "ok" as "loading" | "auth-required" | "ok",
  },
  mockLoadAllPlugins: vi.fn(),
}));

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("./usePluginLoader", () => ({
  loadAllPlugins: mockLoadAllPlugins,
}));

function Probe() {
  const { loading } = usePlugins();
  return <div data-testid="loading">{loading ? "loading" : "done"}</div>;
}

describe("PluginProvider", () => {
  beforeEach(() => {
    authState.role = "user";
    authState.status = "ok";
    mockLoadAllPlugins.mockReset();
    mockLoadAllPlugins.mockResolvedValue({ loaded: 0, failed: [] });
  });

  it("does not request admin plugins for ordinary users", async () => {
    render(
      <PluginProvider>
        <Probe />
      </PluginProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("done");
    });
    expect(mockLoadAllPlugins).not.toHaveBeenCalled();
  });

  it("loads plugins for admins", async () => {
    authState.role = "admin";

    render(
      <PluginProvider>
        <Probe />
      </PluginProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("done");
    });
    expect(mockLoadAllPlugins).toHaveBeenCalledTimes(1);
  });
});
