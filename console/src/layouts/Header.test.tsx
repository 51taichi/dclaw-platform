import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Header from "./Header";

const { authState, themeState } = vi.hoisted(() => ({
  authState: { role: "user" },
  themeState: { isDark: false },
}));

vi.mock("../contexts/ThemeContext", () => ({
  useTheme: () => ({
    isDark: themeState.isDark,
  }),
}));

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => ({
    role: authState.role,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("../components/LanguageSwitcher/index", () => ({
  default: () => <button type="button">Language</button>,
}));

vi.mock("../components/ThemeToggleButton", () => ({
  default: () => <button type="button">Theme</button>,
}));

describe("Header brand logo", () => {
  beforeEach(() => {
    authState.role = "user";
    themeState.isDark = false;
  });

  it("uses the DClaw light wordmark in light mode", () => {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );

    expect(screen.getByAltText("DClaw")).toHaveAttribute(
      "src",
      "/dclaw-logo-light.svg",
    );
  });

  it("uses the DClaw dark wordmark in dark mode", () => {
    themeState.isDark = true;

    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );

    expect(screen.getByAltText("DClaw")).toHaveAttribute(
      "src",
      "/dclaw-logo-dark.svg",
    );
  });

  it("shows concurrency monitoring in the admin header", () => {
    authState.role = "admin";
    render(
      <MemoryRouter initialEntries={["/admin/agents"]}>
        <Header />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("button", { name: "并发监控" }),
    ).toBeInTheDocument();
  });
});
