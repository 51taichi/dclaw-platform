import type { AigcCanvas, AigcCanvasNode } from "../../api/modules/aigcStudio";
import type { CanvasPoint } from "./canvasAssetFactory";
import type { PortSide } from "./domain/componentRegistry";
import { nodeVisualHeight, nodeVisualWidth } from "./canvasNodeUtils";

export const NODE_HANDLE_SIZE = 22;
export const NODE_HANDLE_OUTSET = 18;
export type CanvasHandleCenters = Record<string, CanvasPoint>;

export const canvasHandleCenterKey = (nodeId: string, side: PortSide) =>
  `${nodeId}:${side}`;

const nodeHandleCenterOffset = (side: PortSide) =>
  side === "right"
    ? NODE_HANDLE_OUTSET - NODE_HANDLE_SIZE / 2
    : NODE_HANDLE_SIZE / 2 - NODE_HANDLE_OUTSET;

export function nodeHandleCenterCanvasPoint(
  node: AigcCanvasNode,
  side: PortSide,
) {
  return {
    x:
      node.position.x +
      (side === "right" ? nodeVisualWidth(node) : 0) +
      nodeHandleCenterOffset(side),
    y: node.position.y + nodeVisualHeight(node) / 2,
  };
}

export function nodeHandleCenterSurfacePoint({
  node,
  side,
  viewport,
  scale,
}: {
  node: AigcCanvasNode;
  side: PortSide;
  viewport: AigcCanvas["viewport"];
  scale: number;
}) {
  const point = nodeHandleCenterCanvasPoint(node, side);
  return {
    x: (viewport.x ?? 0) + point.x * scale,
    y: (viewport.y ?? 0) + point.y * scale,
  };
}
