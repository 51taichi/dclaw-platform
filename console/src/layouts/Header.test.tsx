import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
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
    expect(screen.getByRole("tab", { name: "管理后台" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows configured desktop scenes and switches between them", async () => {
    const user = userEvent.setup();
    const onSceneChange = vi.fn();
    render(
      <MemoryRouter>
        <Header
          showSceneTabs
          activeSceneKey="workbench"
          onSceneChange={onSceneChange}
          scenes={[
            {
              key: "ai-customer-service",
              title: "AI客服",
              url: "https://service.example.com/console/?workspace=alice",
              icon: "headset",
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("tab", { name: "工作台" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen
        .getByRole("tab", { name: "AI客服" })
        .querySelector('[data-scene-icon="headset"]'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "AI客服" }));
    expect(onSceneChange).toHaveBeenCalledWith("ai-customer-service");
  });

  it("falls back to the external-link icon for unknown icon names", () => {
    render(
      <MemoryRouter>
        <Header
          showSceneTabs
          activeSceneKey="unknown-scene"
          scenes={[
            {
              key: "unknown-scene",
              title: "旧场景",
              url: "https://legacy.example.com",
              icon: "legacy-icon",
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(
      screen
        .getByRole("tab", { name: "旧场景" })
        .querySelector('[data-scene-icon="external-link"]'),
    ).toBeInTheDocument();
  });

  it("places the admin console after configured scene tabs", () => {
    authState.role = "admin";
    render(
      <MemoryRouter>
        <Header
          showSceneTabs
          scenes={[
            {
              key: "customer-service",
              title: "AI客服",
              url: "https://service.example.com/alice",
            },
            {
              key: "agent-site",
              title: "Agent官网",
              url: "https://site.example.com/alice",
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "工作台",
      "AI客服",
      "Agent官网",
      "管理后台",
    ]);
  });
});
