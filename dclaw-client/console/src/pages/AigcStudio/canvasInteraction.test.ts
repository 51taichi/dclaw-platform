import { describe, expect, it } from "vitest";

import {
  dragNodePosition,
  isCanvasViewportTarget,
  offsetCanvasViewport,
  panCanvasViewport,
} from "./canvasInteraction";

describe("canvasInteraction", () => {
  it("offsets and pans viewport state without changing zoom intent", () => {
    expect(
      offsetCanvasViewport({
        viewport: { x: 10, y: 20, zoom: 0.8 },
        deltaX: -4,
        deltaY: 9,
        fallbackScale: 1,
      }),
    ).toEqual({ x: 6, y: 29, zoom: 0.8 });

    expect(
      panCanvasViewport({
        currentViewport: { x: 0, y: 0, zoom: 0.75 },
        panState: {
          startClientX: 100,
          startClientY: 120,
          startViewportX: 20,
          startViewportY: 30,
        },
        clientX: 118,
        clientY: 90,
        fallbackScale: 1,
      }),
    ).toEqual({ x: 38, y: 0, zoom: 0.75 });
  });

  it("calculates dragged node positions left of the current canvas origin", () => {
    expect(
      dragNodePosition({
        dragState: {
          nodeId: "node-1",
          startClientX: 200,
          startClientY: 160,
          startX: 80,
          startY: 24,
        },
        clientX: 150,
        clientY: 220,
        viewportScale: 0.5,
      }),
    ).toEqual({ x: -20, y: 144 });
  });

  it("allows nodes to be dragged above the current canvas origin", () => {
    expect(
      dragNodePosition({
        dragState: {
          nodeId: "node-1",
          startClientX: 200,
          startClientY: 160,
          startX: 80,
          startY: 24,
        },
        clientX: 210,
        clientY: 100,
        viewportScale: 1,
      }),
    ).toEqual({ x: 90, y: -36 });
  });

  it("filters interactive elements out of viewport gestures", () => {
    const canvas = document.createElement("div");
    const button = document.createElement("button");
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const nodeShell = document.createElement("div");
    nodeShell.dataset.aigcNode = "true";
    button.append(icon);
    canvas.append(button, nodeShell);

    expect(isCanvasViewportTarget(null)).toBe(true);
    expect(isCanvasViewportTarget(canvas)).toBe(true);
    expect(isCanvasViewportTarget(button)).toBe(false);
    expect(isCanvasViewportTarget(icon)).toBe(false);
    expect(isCanvasViewportTarget(nodeShell)).toBe(false);
  });
});
