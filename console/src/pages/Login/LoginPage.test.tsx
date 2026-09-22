import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import LoginPage from "./index";
import { renderWithProviders } from "@/test/common_setup";

const { mockGetStatus, mockCheckAuth, mockNavigate } = vi.hoisted(() => ({
  mockGetStatus: vi.fn().mockResolvedValue({ enabled: true, has_users: true }),
  mockCheckAuth: vi.fn(),
  mockNavigate: vi.fn(),
}));

vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getStatus: mockGetStatus,
    login: vi.fn(),
    register: vi.fn(),
  },
}));

vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => ({ checkAuth: mockCheckAuth }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "login.title": "登录 DClaw",
        "login.usernamePlaceholder": "用户名",
        "login.passwordPlaceholder": "密码",
        "login.usernameRequired": "请输入用户名",
        "login.passwordRequired": "请输入密码",
        "login.submit": "登陆",
        "login.register": "注册",
      })[key] ?? key,
  }),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

describe("LoginPage", () => {
  it("exposes visible text labels independently of decorative images", async () => {
    renderWithProviders(<LoginPage />, { initialEntries: ["/login"] });
    await waitFor(() => expect(mockGetStatus).toHaveBeenCalled());
    const usernameLabel = screen.getByText("用户名", { selector: "label" });
    const passwordLabel = screen.getByText("密码", { selector: "label" });
    expect(usernameLabel).toHaveAttribute(
      "for",
      screen.getByLabelText("用户名").id,
    );
    expect(passwordLabel).toHaveAttribute(
      "for",
      screen.getByLabelText("密码").id,
    );
    expect(screen.getByRole("button", { name: /登\s*陆/ })).toBeVisible();
  });
});
