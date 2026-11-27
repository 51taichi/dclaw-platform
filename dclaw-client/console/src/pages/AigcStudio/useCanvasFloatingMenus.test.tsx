import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useCanvasFloatingMenus } from "./useCanvasFloatingMenus";

describe("useCanvasFloatingMenus", () => {
  it("opens one primary canvas menu at a time", () => {
    const { result } = renderHook(() => useCanvasFloatingMenus());

    act(() => {
      result.current.openAddMenu({
        x: 120,
        y: 140,
        position: { x: 10, y: 20 },
      });
    });

    expect(result.current.addMenuOpen).toBe(true);
    expect(result.current.addMenuAnchor?.position).toEqual({ x: 10, y: 20 });

    act(() => {
      result.current.openCanvasContextMenu({
        x: 200,
        y: 220,
        position: { x: 30, y: 40 },
      });
    });

    expect(result.current.addMenuOpen).toBe(false);
    expect(result.current.addMenuAnchor).toBeNull();
    expect(result.current.canvasContextMenu?.position).toEqual({
      x: 30,
      y: 40,
    });
    expect(result.current.contextMenu).toBeNull();
    expect(result.current.portMenu).toBeNull();
  });

  it("closes all canvas floating menus together", () => {
    const { result } = renderHook(() => useCanvasFloatingMenus());

    act(() => {
      result.current.setQuickTemplateMenu({
        x: 80,
        y: 90,
        position: { x: 1, y: 2 },
      });
      result.current.openPortMenu({
        nodeId: "node-1",
        side: "right",
        x: 160,
        y: 180,
      });
      result.current.closeCanvasMenus();
    });

    expect(result.current.quickTemplateMenu).toBeNull();
    expect(result.current.portMenu).toBeNull();
    expect(result.current.addMenuOpen).toBe(false);
    expect(result.current.addMenuAnchor).toBeNull();
    expect(result.current.contextMenu).toBeNull();
    expect(result.current.canvasContextMenu).toBeNull();
  });
});
