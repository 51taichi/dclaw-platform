import type { AigcCanvas, AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  canvasHandleCenterKey,
  nodeHandleCenterSurfacePoint,
  type CanvasHandleCenters,
} from "./canvasHandleGeometry";
import { nodeVisualHeight, nodeVisualWidth } from "./canvasNodeUtils";

export type CanvasEdgeLine = {
  id: string;
  path: string;
};

export type CanvasSurfaceSize = {
  visibleWidth: number;
  visibleHeight: number;
};

export function buildCanvasEdgeLines(
  canvas: AigcCanvas | null,
  viewportScale: number,
  handleCenters: CanvasHandleCenters = {},
): CanvasEdgeLine[] {
  if (!canvas) return [];
  const nodeMap = new Map(canvas.nodes.map((node) => [node.id, node]));
  return canvas.edges.flatMap((edge) => {
    const source = nodeMap.get(edge.source);
    const target = nodeMap.get(edge.target);
    if (!source || !target) return [];
    const start =
      handleCenters[canvasHandleCenterKey(source.id, "right")] ??
      nodeHandleCenterSurfacePoint({
        node: source,
        side: "right",
        viewport: canvas.viewport,
        scale: viewportScale,
      });
    const end =
      handleCenters[canvasHandleCenterKey(target.id, "left")] ??
      nodeHandleCenterSurfacePoint({
        node: target,
        side: "left",
        viewport: canvas.viewport,
        scale: viewportScale,
      });
    const x1 = start.x;
    const y1 = start.y;
    const x2 = end.x;
    const y2 = end.y;
    const horizontalDistance = Math.abs(x2 - x1);
    const curve = Math.min(180, Math.max(64, horizontalDistance * 0.42));
    return [
      {
        id: edge.id,
        path: `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${
          x2 - curve
        } ${y2}, ${x2} ${y2}`,
      },
    ];
  });
}

export function surfacePointToCanvasPoint({
  point,
  viewport,
  scale,
  min = 24,
}: {
  point: { x: number; y: number };
  viewport: AigcCanvas["viewport"];
  scale: number;
  min?: number;
}) {
  return {
    x: Math.max(min, (point.x - (viewport.x ?? 0)) / scale),
    y: Math.max(min, (point.y - (viewport.y ?? 0)) / scale),
  };
}

export function boundedViewportScale(nextScale: number) {
  return Math.min(2, Math.max(0.1, Number(nextScale.toFixed(2))));
}

export function defaultNodePositionInViewport({
  viewport,
  scale,
  visibleWidth,
  visibleHeight,
  nodeWidth,
  nodeHeight,
  nodeCount,
  min = 24,
}: {
  viewport: AigcCanvas["viewport"];
  scale: number;
  nodeWidth: number;
  nodeHeight: number;
  nodeCount: number;
  min?: number;
} & CanvasSurfaceSize) {
  const safeScale = Math.max(0.1, scale || viewport.zoom || 1);
  const centerX = (visibleWidth / 2 - (viewport.x ?? 0)) / safeScale;
  const centerY = (visibleHeight / 2 - (viewport.y ?? 0)) / safeScale;
  const stagger = (nodeCount % 6) * 28;
  return {
    x: Math.max(min, Math.round(centerX - nodeWidth / 2 + stagger)),
    y: Math.max(min, Math.round(centerY - nodeHeight / 2 + stagger)),
  };
}

export function zoomViewportAroundSurfacePoint({
  viewport,
  surfacePoint,
  currentScale,
  nextScale,
}: {
  viewport: AigcCanvas["viewport"];
  surfacePoint: { x: number; y: number };
  currentScale: number;
  nextScale: number;
}): AigcCanvas["viewport"] {
  const safeCurrentScale = Math.max(0.1, currentScale || viewport.zoom || 1);
  const boundedScale = boundedViewportScale(nextScale);
  const canvasX = (surfacePoint.x - (viewport.x ?? 0)) / safeCurrentScale;
  const canvasY = (surfacePoint.y - (viewport.y ?? 0)) / safeCurrentScale;
  return {
    ...viewport,
    x: surfacePoint.x - canvasX * boundedScale,
    y: surfacePoint.y - canvasY * boundedScale,
    zoom: boundedScale,
  };
}

export function fitViewportToNodes({
  canvas,
  visibleWidth,
  visibleHeight,
  padding = 96,
}: {
  canvas: AigcCanvas;
  padding?: number;
} & CanvasSurfaceSize): AigcCanvas["viewport"] | null {
  if (canvas.nodes.length === 0) return null;
  const minX = Math.min(...canvas.nodes.map((node) => node.position.x));
  const minY = Math.min(...canvas.nodes.map((node) => node.position.y));
  const maxX = Math.max(
    ...canvas.nodes.map((node) => node.position.x + nodeVisualWidth(node)),
  );
  const maxY = Math.max(
    ...canvas.nodes.map((node) => node.position.y + nodeVisualHeight(node)),
  );
  const boundsWidth = Math.max(1, maxX - minX);
  const boundsHeight = Math.max(1, maxY - minY);
  const scale = Math.min(
    1.4,
    Math.max(
      0.1,
      Number(
        Math.min(
          (visibleWidth - padding * 2) / boundsWidth,
          (visibleHeight - padding * 2) / boundsHeight,
        ).toFixed(2),
      ),
    ),
  );
  return {
    ...canvas.viewport,
    x: visibleWidth / 2 - (minX + boundsWidth / 2) * scale,
    y: visibleHeight / 2 - (minY + boundsHeight / 2) * scale,
    zoom: scale,
  };
}

export function centerViewportOnNode({
  canvas,
  node,
  visibleWidth,
  visibleHeight,
  scale,
}: {
  canvas: AigcCanvas;
  node: AigcCanvasNode;
  scale: number;
} & CanvasSurfaceSize): AigcCanvas["viewport"] {
  return {
    ...canvas.viewport,
    x: visibleWidth / 2 - (node.position.x + nodeVisualWidth(node) / 2) * scale,
    y: visibleHeight / 2 - (node.position.y + 130) * scale,
    zoom: scale,
  };
}
