import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasRail, type RailPanel } from "./CanvasRail";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("CanvasRail", () => {
  it("routes add and panel actions to the canvas controller", () => {
    const toggleAddMenu = vi.fn();
    const selectPanel = vi.fn();

    render(
      <CanvasRail
        railPanel={"assets" as RailPanel}
        t={t}
        onToggleAddMenu={toggleAddMenu}
        onSelectPanel={selectPanel}
        onOpenStyleLibrary={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText("添加节点"));
    expect(toggleAddMenu).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByLabelText("打开我的资产"));
    expect(selectPanel).toHaveBeenCalledWith("assets");

    fireEvent.click(screen.getByLabelText("打开历史记录"));
    expect(selectPanel).toHaveBeenCalledWith("history");
  });

  it("exposes a dedicated style library entry", () => {
    const openStyleLibrary = vi.fn();

    render(
      <CanvasRail
        railPanel={null}
        t={t}
        onToggleAddMenu={vi.fn()}
        onSelectPanel={vi.fn()}
        onOpenStyleLibrary={openStyleLibrary}
      />,
    );

    fireEvent.click(screen.getByLabelText("打开风格库"));

    expect(openStyleLibrary).toHaveBeenCalledTimes(1);
  });

  it("marks the active rail panel", () => {
    const { rerender } = render(
      <CanvasRail
        railPanel="workflows"
        t={t}
        onToggleAddMenu={vi.fn()}
        onSelectPanel={vi.fn()}
        onOpenStyleLibrary={vi.fn()}
      />,
    );

    const workflowsButton = screen.getByLabelText("打开我的工具箱");
    expect(workflowsButton.className).toContain("railButtonActive");

    rerender(
      <CanvasRail
        railPanel={null}
        t={t}
        onToggleAddMenu={vi.fn()}
        onSelectPanel={vi.fn()}
        onOpenStyleLibrary={vi.fn()}
      />,
    );

    expect(workflowsButton.className).not.toContain("railButtonActive");
  });
});
