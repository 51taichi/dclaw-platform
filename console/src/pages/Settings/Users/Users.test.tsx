import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  const modalCreateButton = () => {
    const buttons = screen.getAllByRole("button", { name: /创\s*建/ });
    return buttons[buttons.length - 1];
  };
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminUsersApi.listUsers).mockResolvedValue([
      {
        id: 24,
        username: "dingmai",
        display_name: "丁麦",
        phone_number: "+8613800138000",
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
    expect(screen.getByText("丁麦")).toBeInTheDocument();
    expect(screen.getByText("+8613800138000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重置密码/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /删除/ })).toBeInTheDocument();
  });

  it("requires and submits login id, name, and mainland mobile", async () => {
    const user = userEvent.setup();
    vi.mocked(adminUsersApi.createUser).mockResolvedValue({
      id: 25, username: "alice", display_name: "Alice Chen",
      phone_number: "+8613900139000", role: "user", created_at: "2026-09-29T00:00:00Z",
    });
    render(<UsersPage />);
    await user.click(screen.getByRole("button", { name: /创建用户/ }));

    expect(screen.getByLabelText("登录 ID")).toBeInTheDocument();
    expect(screen.getByLabelText("姓名")).toBeInTheDocument();
    expect(screen.getByLabelText("手机号")).toBeInTheDocument();
    await user.click(modalCreateButton());
    expect(await screen.findByText("请输入姓名！")).toBeInTheDocument();
    expect(screen.getByText("请输入手机号！")).toBeInTheDocument();

    await user.type(screen.getByLabelText("登录 ID"), "alice");
    await user.type(screen.getByLabelText("姓名"), "  Alice Chen  ");
    await user.type(screen.getByLabelText("手机号"), "13900139000");
    await user.type(screen.getByLabelText("密码"), "secret");
    await user.click(modalCreateButton());
    await waitFor(() => expect(adminUsersApi.createUser).toHaveBeenCalledWith({
      username: "alice", display_name: "Alice Chen", phone_number: "13900139000",
      password: "secret", role: "user",
    }));
  });

  it("rejects a malformed mainland mobile", async () => {
    const user = userEvent.setup();
    render(<UsersPage />);
    await user.click(screen.getByRole("button", { name: /创建用户/ }));
    await user.type(screen.getByLabelText("手机号"), "12345");
    await user.click(modalCreateButton());
    expect(await screen.findByText("请输入有效的中国大陆手机号！")).toBeInTheDocument();
    expect(adminUsersApi.createUser).not.toHaveBeenCalled();
  });
});
