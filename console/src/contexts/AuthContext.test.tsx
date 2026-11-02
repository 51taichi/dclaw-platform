import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthContext";

const { clearAuthToken, getApiToken, getStatus } = vi.hoisted(() => ({
  clearAuthToken: vi.fn(),
  getApiToken: vi.fn(),
  getStatus: vi.fn(),
}));

vi.mock("../api/modules/auth", () => ({
  authApi: { getStatus },
}));

vi.mock("../api/config", () => ({
  clearAuthToken,
  getApiToken,
  getApiUrl: (path: string) => path,
}));

function AuthState() {
  const { username, role, status, logout } = useAuth();

  return (
    <div>
      <span>{`${status}:${username ?? "none"}:${role ?? "none"}`}</span>
      <button type="button" onClick={logout}>
        logout
      </button>
    </div>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getApiToken.mockReturnValue("token");
    getStatus.mockResolvedValue({ enabled: true, has_users: true });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          valid: true,
          username: "alice",
          role: "admin",
          scenes: [],
        }),
      }),
    );
  });

  it("exposes the verified username and clears it on logout", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <AuthState />
      </AuthProvider>,
    );

    expect(await screen.findByText("ok:alice:admin")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "logout" }));

    await waitFor(() =>
      expect(screen.getByText("auth-required:none:none")).toBeInTheDocument(),
    );
    expect(clearAuthToken).toHaveBeenCalledOnce();
  });
});
