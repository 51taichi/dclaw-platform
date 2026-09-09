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

export function resolveWorkflowReviewAssets(
  nodes: AigcCanvasNode[],
  edges: AigcCanvasEdge[],
  nodeIds: string[],
): { node_id: string; asset_id: string }[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const collect = (nodeId: string, visited: Set<string>): string[] => {
    if (visited.has(nodeId)) return [];
    visited.add(nodeId);
    const outputs = byId.get(nodeId)?.data.outputs;
    const ids = Array.isArray(outputs)
      ? outputs.flatMap((item) =>
          typeof item?.id === "string" ? [item.id] : [],
        )
      : [];
    if (ids.length) return ids;
    if (byId.get(nodeId)?.type !== "output") return [];
    return edges
      .filter((edge) => edge.target === nodeId)
      .flatMap((edge) => collect(edge.source, visited));
  };
  return nodeIds.flatMap((nodeId) => {
    const ids = [...new Set(collect(nodeId, new Set()))];
    if (!ids.length) throw new Error("审核清单中的节点尚无可提交产物");
    return ids.map((assetId) => ({ node_id: nodeId, asset_id: assetId }));
  });
}
