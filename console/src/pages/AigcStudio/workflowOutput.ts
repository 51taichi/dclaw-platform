import type {
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";

const assetIdFromNode = (node: AigcCanvasNode | undefined) => {
  const outputs = Array.isArray(node?.data.outputs) ? node.data.outputs : [];
  const first = outputs.find(
    (item) => item && typeof item === "object" && "id" in item,
  ) as { id?: unknown } | undefined;
  return typeof first?.id === "string" ? first.id.trim() : "";
};

export function resolveWorkflowOutputAssetId(
  nodes: AigcCanvasNode[],
  edges: AigcCanvasEdge[],
  outputNodeId: string,
): string {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, string[]>();
  edges.forEach((edge) => {
    incoming.set(edge.target, [
      ...(incoming.get(edge.target) ?? []),
      edge.source,
    ]);
  });
  const visited = new Set<string>();
  const visit = (nodeId: string): string => {
    if (visited.has(nodeId)) return "";
    visited.add(nodeId);
    const own = assetIdFromNode(byId.get(nodeId));
    if (own) return own;
    for (const sourceId of incoming.get(nodeId) ?? []) {
      const upstream = visit(sourceId);
      if (upstream) return upstream;
    }
    return "";
  };
  return visit(outputNodeId);
}
