import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";
import type { CanvasPoint } from "./canvasAssetFactory";
import type { PortSide } from "./domain/componentRegistry";

export function repositionTemplateNodes(
  nodes: AigcCanvasNode[],
  anchorPosition?: CanvasPoint,
) {
  if (!anchorPosition) return nodes;
  const minX = Math.min(...nodes.map((node) => node.position.x));
  const minY = Math.min(...nodes.map((node) => node.position.y));
  return nodes.map((node) => ({
    ...node,
    position: {
      x: anchorPosition.x + (node.position.x - minX),
      y: anchorPosition.y + (node.position.y - minY),
    },
  }));
}

export function appendTemplateParts({
  canvas,
  nodes,
  edges,
}: {
  canvas: AigcCanvas;
  nodes: AigcCanvasNode[];
  edges: AigcCanvasEdge[];
}): AigcCanvas {
  return {
    ...canvas,
    nodes: [...canvas.nodes, ...nodes],
    edges: [...canvas.edges, ...edges],
  };
}

export function portNodePosition({
  anchorNode,
  side,
  anchorWidth,
  createdWidth,
}: {
  anchorNode: AigcCanvasNode;
  side: PortSide;
  anchorWidth: number;
  createdWidth: number;
}): CanvasPoint {
  return {
    x:
      side === "left"
        ? Math.max(0, anchorNode.position.x - createdWidth - 170)
        : anchorNode.position.x + anchorWidth + 170,
    y: anchorNode.position.y,
  };
}

export function createPortEdge({
  anchorNode,
  createdNode,
  side,
  role,
}: {
  anchorNode: AigcCanvasNode;
  createdNode: AigcCanvasNode;
  side: PortSide;
  role: string;
}): AigcCanvasEdge {
  return {
    id:
      side === "right"
        ? `edge-${anchorNode.id}-${createdNode.id}`
        : `edge-${createdNode.id}-${anchorNode.id}`,
    source: side === "right" ? anchorNode.id : createdNode.id,
    target: side === "right" ? createdNode.id : anchorNode.id,
    sourceHandle: "right",
    targetHandle: "left",
    data: { role },
  };
}

export function appendPortNode({
  canvas,
  node,
  edge,
}: {
  canvas: AigcCanvas;
  node: AigcCanvasNode;
  edge: AigcCanvasEdge;
}): AigcCanvas {
  return {
    ...canvas,
    nodes: [...canvas.nodes, node],
    edges: [...canvas.edges, edge],
  };
}
