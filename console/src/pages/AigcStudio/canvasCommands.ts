import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";

export type DeletedNodeSnapshot = {
  canvasId: string;
  node: AigcCanvasNode;
  edges: AigcCanvasEdge[];
  selectedNodeId: string | null;
};

export function cloneCanvasNode({
  node,
  suffix,
  offset = { x: 44, y: 44 },
  fallbackTitle,
}: {
  node: AigcCanvasNode;
  suffix: string;
  offset?: { x: number; y: number };
  fallbackTitle?: string;
}): AigcCanvasNode {
  return {
    ...node,
    id: `${node.type}-${suffix}`,
    position: {
      x: node.position.x + offset.x,
      y: node.position.y + offset.y,
    },
    data: {
      ...node.data,
      title: `${String(node.data.title ?? fallbackTitle ?? node.type)} 副本`,
    },
  };
}

export function pasteCanvasNode({
  canvas,
  node,
  suffix,
  fallbackTitle,
}: {
  canvas: AigcCanvas;
  node: AigcCanvasNode;
  suffix: string;
  fallbackTitle?: string;
}) {
  const copy = cloneCanvasNode({
    node,
    suffix,
    offset: { x: 72, y: 72 },
    fallbackTitle,
  });
  return {
    canvas: {
      ...canvas,
      nodes: [...canvas.nodes, copy],
    },
    node: copy,
  };
}

export function duplicateCanvasNodeWithEdges({
  canvas,
  node,
  suffix,
  fallbackTitle,
}: {
  canvas: AigcCanvas;
  node: AigcCanvasNode;
  suffix: string;
  fallbackTitle?: string;
}) {
  const copy = cloneCanvasNode({ node, suffix, fallbackTitle });
  const copiedEdges = canvas.edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => ({
      ...edge,
      id: `edge-${edge.id}-${copy.id}`,
      source: edge.source === node.id ? copy.id : edge.source,
      target: edge.target === node.id ? copy.id : edge.target,
    }));

  return {
    canvas: {
      ...canvas,
      nodes: [...canvas.nodes, copy],
      edges: [...canvas.edges, ...copiedEdges],
    },
    node: copy,
  };
}

export function deleteCanvasNode({
  canvas,
  nodeId,
  selectedNodeId,
}: {
  canvas: AigcCanvas;
  nodeId: string;
  selectedNodeId: string | null;
}) {
  const deletedNode = canvas.nodes.find((node) => node.id === nodeId);
  if (!deletedNode) return null;
  const deletedEdges = canvas.edges.filter(
    (edge) => edge.source === nodeId || edge.target === nodeId,
  );
  const updatedCanvas = {
    ...canvas,
    nodes: canvas.nodes.filter((node) => node.id !== nodeId),
    edges: canvas.edges.filter(
      (edge) => edge.source !== nodeId && edge.target !== nodeId,
    ),
  };
  return {
    canvas: updatedCanvas,
    snapshot: {
      canvasId: canvas.id,
      node: deletedNode,
      edges: deletedEdges,
      selectedNodeId,
    },
    nextSelectedNodeId: selectedNodeId === nodeId ? null : selectedNodeId,
  };
}

export function restoreDeletedCanvasNode({
  canvas,
  snapshot,
}: {
  canvas: AigcCanvas;
  snapshot: DeletedNodeSnapshot;
}) {
  if (snapshot.canvasId !== canvas.id) return null;
  if (canvas.nodes.some((node) => node.id === snapshot.node.id)) return null;
  return {
    canvas: {
      ...canvas,
      nodes: [...canvas.nodes, snapshot.node],
      edges: [...canvas.edges, ...snapshot.edges],
    },
    selectedNodeId: snapshot.selectedNodeId,
  };
}
