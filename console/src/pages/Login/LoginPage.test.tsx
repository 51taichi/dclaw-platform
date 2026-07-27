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
  it("renders the designed login composition without the extra header logo", async () => {
    renderWithProviders(<LoginPage />, { initialEntries: ["/login"] });

    await waitFor(() => expect(mockGetStatus).toHaveBeenCalled());

    expect(screen.getByRole("main")).toHaveAttribute(
      "data-design-ratio",
      "8000:4500",
    );
    const hello = screen.getByText("Hello ~");
    expect(hello).toBeInTheDocument();
    expect(hello.parentElement).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByAltText("登录 DClaw")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("用户名")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /登\s*陆/ })).toBeInTheDocument();
    expect(screen.queryByAltText("DClaw")).not.toBeInTheDocument();
  });

  it("keeps the submit button readable until the image asset is ready", async () => {
    renderWithProviders(<LoginPage />, { initialEntries: ["/login"] });

    await waitFor(() => expect(mockGetStatus).toHaveBeenCalled());

    const submitButton = screen.getByRole("button", { name: /登\s*陆/ });
    expect(submitButton.className).not.toContain("loginButtonImage");
  });
});
