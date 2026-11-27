import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { CanvasMinimap } from "./CanvasMinimap";

const t = ((
  _key: string,
  fallback?: string,
  options?: { count?: number; title?: string },
) => {
  let text = fallback ?? _key;
  if (options?.count !== undefined) {
    text = text.replace("{{count}}", String(options.count));
  }
  if (options?.title !== undefined) {
    text = text.replace("{{title}}", String(options.title));
  }
  return text;
}) as never;

const node = (
  id: string,
  position: { x: number; y: number },
  title: string,
): AigcCanvasNode => ({
  id,
  type: "prompt",
  position,
  data: { title },
});

describe("CanvasMinimap", () => {
  it("routes compact dock actions and shows current zoom", () => {
    const fit = vi.fn();
    const centerSelected = vi.fn();
    const toggle = vi.fn();
    const zoom = vi.fn();

    render(
      <CanvasMinimap
        minimapOpen={false}
        viewportScale={0.75}
        viewport={{ x: 0, y: 0, zoom: 0.75 }}
        visibleWidth={1200}
        visibleHeight={760}
        nodes={[]}
        selectedNode={undefined}
        selectedNodeId={null}
        canvasBounds={{ minX: 0, minY: 0, width: 1, height: 1 }}
        t={t}
        onFitViewport={fit}
        onCenterSelectedNode={centerSelected}
        onToggleMinimap={toggle}
        onUpdateViewportScale={zoom}
        onCenterNode={vi.fn()}
        onMoveViewport={vi.fn()}
      />,
    );

    const minimapButton = screen.getByRole("button", { name: "画布小地图" });
    expect(minimapButton).toHaveAttribute("title", "画布小地图");
    expect(minimapButton).toHaveAttribute("data-tooltip", "画布小地图");
    expect(screen.getByTestId("aigc-minimap-dock")).toContainElement(
      minimapButton,
    );

    fireEvent.click(screen.getByLabelText("适配全部"));
    fireEvent.click(minimapButton);
    fireEvent.click(screen.getByLabelText("缩小"));
    fireEvent.click(screen.getByLabelText("放大"));

    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("75%")).toHaveAttribute(
      "data-testid",
      "aigc-zoom-ratio",
    );
    expect(screen.getByLabelText("回到选中")).toBeDisabled();
    expect(fit).toHaveBeenCalledTimes(1);
    expect(centerSelected).not.toHaveBeenCalled();
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(zoom).toHaveBeenCalledWith(0.65);
    expect(zoom).toHaveBeenCalledWith(0.85);
  });

  it("zooms from mouse wheel hover on the minimap dock", () => {
    const zoom = vi.fn();

    render(
      <CanvasMinimap
        minimapOpen={false}
        viewportScale={0.75}
        viewport={{ x: 0, y: 0, zoom: 0.75 }}
        visibleWidth={1200}
        visibleHeight={760}
        nodes={[]}
        selectedNode={undefined}
        selectedNodeId={null}
        canvasBounds={{ minX: 0, minY: 0, width: 1, height: 1 }}
        t={t}
        onFitViewport={vi.fn()}
        onCenterSelectedNode={vi.fn()}
        onToggleMinimap={vi.fn()}
        onUpdateViewportScale={zoom}
        onCenterNode={vi.fn()}
        onMoveViewport={vi.fn()}
      />,
    );

    fireEvent.wheel(screen.getByTestId("aigc-minimap-dock"), {
      deltaY: -120,
    });

    expect(zoom).toHaveBeenCalledTimes(1);
    expect(zoom.mock.calls[0]?.[0]).toBeGreaterThan(0.75);
  });

  it("renders minimap nodes and routes node centering", () => {
    const centerNode = vi.fn();
    const firstNode = node("node-1", { x: 10, y: 20 }, "开场提示词");
    const secondNode = node("node-2", { x: 110, y: 120 }, "图片节点");

    render(
      <CanvasMinimap
        minimapOpen
        viewportScale={1}
        viewport={{ x: 0, y: 0, zoom: 1 }}
        visibleWidth={1200}
        visibleHeight={760}
        nodes={[firstNode, secondNode]}
        selectedNode={secondNode}
        selectedNodeId="node-2"
        canvasBounds={{ minX: 10, minY: 20, width: 200, height: 200 }}
        t={t}
        onFitViewport={vi.fn()}
        onCenterSelectedNode={vi.fn()}
        onToggleMinimap={vi.fn()}
        onUpdateViewportScale={vi.fn()}
        onCenterNode={centerNode}
        onMoveViewport={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText("定位节点 图片节点"));

    expect(screen.getByTestId("aigc-minimap")).toBeInTheDocument();
    expect(screen.queryByText("Mini Map")).not.toBeInTheDocument();
    expect(screen.queryByText("2 个节点")).not.toBeInTheDocument();
    expect(centerNode).toHaveBeenCalledWith(secondNode);
  });

  it("moves the canvas viewport by dragging inside the minimap", () => {
    const moveViewport = vi.fn();
    const firstNode = node("node-1", { x: 0, y: 0 }, "开场提示词");

    render(
      <CanvasMinimap
        minimapOpen
        viewportScale={1}
        viewport={{ x: 0, y: 0, zoom: 1 }}
        visibleWidth={400}
        visibleHeight={200}
        nodes={[firstNode]}
        selectedNode={firstNode}
        selectedNodeId="node-1"
        canvasBounds={{ minX: 0, minY: 0, width: 800, height: 400 }}
        t={t}
        onFitViewport={vi.fn()}
        onCenterSelectedNode={vi.fn()}
        onToggleMinimap={vi.fn()}
        onUpdateViewportScale={vi.fn()}
        onCenterNode={vi.fn()}
        onMoveViewport={moveViewport}
      />,
    );

    const minimapCanvas = screen.getByTestId("aigc-minimap-canvas");
    Object.defineProperty(minimapCanvas, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 160,
        height: 100,
        right: 160,
        bottom: 100,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }),
    });

    fireEvent.mouseDown(minimapCanvas, { clientX: 80, clientY: 50 });
    fireEvent.mouseMove(window, { clientX: 120, clientY: 50 });
    fireEvent.mouseUp(window);

    expect(moveViewport).toHaveBeenCalled();
    const movedViewport =
      moveViewport.mock.calls[moveViewport.mock.calls.length - 1]?.[0];
    expect(movedViewport).toEqual(
      expect.objectContaining({
        zoom: 1,
      }),
    );
    expect(movedViewport.x).toBeLessThan(0);
  });
});
