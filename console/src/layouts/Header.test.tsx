import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Header from "./Header";

const { themeState } = vi.hoisted(() => ({
  themeState: { isDark: false },
}));

vi.mock("../contexts/ThemeContext", () => ({
  useTheme: () => ({
    isDark: themeState.isDark,
  }),
}));

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => ({
    role: "user",
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
});
