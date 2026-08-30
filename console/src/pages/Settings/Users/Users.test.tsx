import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import UsersPage from "./index";

vi.mock("../../../api/modules/adminUsers", () => ({
  adminUsersApi: {
    listUsers: vi.fn(),
    createUser: vi.fn(),
    resetPassword: vi.fn(),
    deleteUser: vi.fn(),
  },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: vi.fn(), success: vi.fn() },
  }),
}));

describe("UsersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminUsersApi.listUsers).mockResolvedValue([
      {
        id: 24,
        username: "dingmai",
        role: "user",
        created_at: "2026-08-28T12:53:23Z",
      },
    ]);
  });

  it("matches the shared settings page structure", async () => {
    render(<UsersPage />);

    expect(screen.getByText("设置")).toBeInTheDocument();
    expect(screen.getByText("用户管理")).toBeInTheDocument();
    expect(screen.getByText("用户列表")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /创建用户/ }),
    ).toBeInTheDocument();
    expect(await screen.findByText("dingmai")).toBeInTheDocument();
  });
});
