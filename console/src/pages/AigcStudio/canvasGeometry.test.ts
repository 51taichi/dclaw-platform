import { describe, expect, it } from "vitest";

import type { AigcCanvas, AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  buildCanvasEdgeLines,
  centerViewportOnNode,
  defaultNodePositionInViewport,
  fitViewportToNodes,
  zoomViewportAroundSurfacePoint,
  surfacePointToCanvasPoint,
} from "./canvasGeometry";
import { canvasHandleCenterKey } from "./canvasHandleGeometry";

const promptNode: AigcCanvasNode = {
  id: "prompt-1",
  type: "prompt",
  position: { x: 100, y: 80 },
  data: {},
};

const imageNode: AigcCanvasNode = {
  id: "image-1",
  type: "image_generate",
  position: { x: 640, y: 100 },
  data: {},
};

const longImageNode: AigcCanvasNode = {
  id: "long-1",
  type: "long_image_export",
  position: { x: 1260, y: 210 },
  data: {},
};

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [promptNode, imageNode],
  edges: [
    {
      id: "edge-1",
      source: "prompt-1",
      target: "image-1",
      sourceHandle: "right",
      targetHandle: "left",
    },
  ],
  viewport: { x: 20, y: 30, zoom: 0.5 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasGeometry", () => {
  it("builds scaled edge paths from plus handle centers", () => {
    expect(buildCanvasEdgeLines(canvasFixture(), 0.5)).toEqual([
      {
        id: "edge-1",
        path: "M 273.5 115 C 337.5 115, 272.5 158.75, 336.5 158.75",
      },
    ]);
  });

  it("anchors edge paths at the plus handle centers", () => {
    const [line] = buildCanvasEdgeLines(canvasFixture(), 1);

    expect(line?.path).toContain("M 527 200");
    expect(line?.path.endsWith("653 287.5")).toBe(true);
  });

  it("uses the rendered long-image node height for its left plus handle", () => {
    const [line] = buildCanvasEdgeLines(
      {
        ...canvasFixture(),
        nodes: [imageNode, longImageNode],
        edges: [
          {
            id: "edge-image-long",
            source: "image-1",
            target: "long-1",
            sourceHandle: "right",
            targetHandle: "left",
          },
        ],
        viewport: { x: 0, y: 0, zoom: 1 },
      },
      1,
    );

    expect(line?.path).toBe("M 1207 257.5 C 1271 257.5, 1189 290, 1253 290");
  });

  it("uses measured plus handle centers before node-height fallbacks", () => {
    const [line] = buildCanvasEdgeLines(canvasFixture(), 1, {
      [canvasHandleCenterKey("prompt-1", "right")]: { x: 111, y: 222 },
      [canvasHandleCenterKey("image-1", "left")]: { x: 333, y: 444 },
    });

    expect(line?.path).toBe("M 111 222 C 204.24 222, 239.76 444, 333 444");
  });

  it("converts surface points into clamped canvas coordinates", () => {
    expect(
      surfacePointToCanvasPoint({
        point: { x: 8, y: 110 },
        viewport: { x: 20, y: 30, zoom: 0.5 },
        scale: 0.5,
      }),
    ).toEqual({ x: 24, y: 160 });
  });

  it("calculates fit-all and center-node viewports", () => {
    expect(
      fitViewportToNodes({
        canvas: canvasFixture(),
        visibleWidth: 1200,
        visibleHeight: 760,
      }),
    ).toEqual({ x: 2, y: 152.29999999999998, zoom: 0.92 });

    expect(
      centerViewportOnNode({
        canvas: canvasFixture(),
        node: imageNode,
        visibleWidth: 1200,
        visibleHeight: 760,
        scale: 0.5,
      }),
    ).toEqual({ x: 140, y: 265, zoom: 0.5 });
  });

  it("places newly created nodes inside the current viewport", () => {
    expect(
      defaultNodePositionInViewport({
        viewport: { x: -1800, y: -900, zoom: 0.5 },
        scale: 0.5,
        visibleWidth: 1200,
        visibleHeight: 760,
        nodeWidth: 350,
        nodeHeight: 260,
        nodeCount: 13,
      }),
    ).toEqual({ x: 4653, y: 2458 });
  });

  it("zooms around a surface point without losing the focused canvas point", () => {
    const viewport = { x: -200, y: -100, zoom: 1 };
    const point = { x: 500, y: 300 };
    const before = surfacePointToCanvasPoint({
      point,
      viewport,
      scale: 1,
      min: Number.NEGATIVE_INFINITY,
    });
    const afterViewport = zoomViewportAroundSurfacePoint({
      viewport,
      surfacePoint: point,
      currentScale: 1,
      nextScale: 1.5,
    });
    const after = surfacePointToCanvasPoint({
      point,
      viewport: afterViewport,
      scale: 1.5,
      min: Number.NEGATIVE_INFINITY,
    });

    expect(afterViewport).toEqual({ x: -550, y: -300, zoom: 1.5 });
    expect(after).toEqual(before);
  });
});
