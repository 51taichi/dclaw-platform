import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ClientLayout from "./ClientLayout";

vi.mock("./Header", () => ({
  default: () => <div data-testid="header" />,
}));

vi.mock("./Sidebar", () => ({
  default: ({ selectedKey }: { selectedKey: string }) => (
    <div data-testid="sidebar" data-selected-key={selectedKey} />
  ),
}));

vi.mock("../components/ConsolePollService", () => ({
  default: () => null,
}));

vi.mock("../plugins/PluginContext", () => ({
  usePlugins: () => ({ pluginRoutes: [] }),
}));

vi.mock("../pages/Chat", () => ({
  default: () => <div data-testid="legacy-chat-page">Legacy Chat</div>,
}));

vi.mock("../pages/Claw", () => ({
  default: () => <div data-testid="claw-page">Claw</div>,
}));

vi.mock("../pages/Workbench", () => ({
  default: () => <div data-testid="workbench-page">Workbench</div>,
}));

vi.mock("../pages/Task", () => ({
  default: () => <div data-testid="task-page">Task</div>,
}));

vi.mock("../pages/AigcStudio", () => ({
  default: () => <div data-testid="aigc-studio-page">AIGC Studio</div>,
}));

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <ClientLayout />
    </MemoryRouter>,
  );
}

describe("ClientLayout routing", () => {
  it("redirects the retired /chat route to workbench instead of rendering the old chat page", async () => {
    renderAt("/chat");

    expect(await screen.findByTestId("workbench-page")).toBeInTheDocument();
    expect(screen.queryByTestId("legacy-chat-page")).not.toBeInTheDocument();
  });

  it("keeps task and claw routes available", async () => {
    const taskView = renderAt("/task/task-id");
    expect(await screen.findByTestId("task-page")).toBeInTheDocument();
    taskView.unmount();

    renderAt("/claw/claw-id");
    expect(await screen.findByTestId("claw-page")).toBeInTheDocument();
  });
});
