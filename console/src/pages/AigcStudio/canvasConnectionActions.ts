import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";
import {
  enabledPortTypesForNode,
  type PortSide,
} from "./domain/componentRegistry";
import {
  downstreamDataFromSource,
  edgeRoleForSource,
} from "./canvasPortMapping";
import type { Translate } from "./canvasNodeUtils";

export type PortConnectionEndpoint = {
  sourceNode: AigcCanvasNode;
  targetNode: AigcCanvasNode;
};

export function portConnectionEndpoint({
  anchorNode,
  dropNode,
  side,
}: {
  anchorNode: AigcCanvasNode;
  dropNode: AigcCanvasNode;
  side: PortSide;
}): PortConnectionEndpoint | null {
  if (anchorNode.id === dropNode.id) return null;
  return side === "right"
    ? { sourceNode: anchorNode, targetNode: dropNode }
    : { sourceNode: dropNode, targetNode: anchorNode };
}

export function canConnectPortNodes({
  sourceNode,
  targetNode,
}: PortConnectionEndpoint) {
  return enabledPortTypesForNode(sourceNode, "right").includes(targetNode.type);
}

export function createPortConnectionEdge({
  sourceNode,
  targetNode,
}: PortConnectionEndpoint): AigcCanvasEdge {
  return {
    id: `edge-${sourceNode.id}-${targetNode.id}`,
    source: sourceNode.id,
    target: targetNode.id,
    sourceHandle: "right",
    targetHandle: "left",
    data: { role: edgeRoleForSource(sourceNode) },
  };
}

function targetDataForPortConnection(
  t: Translate,
  sourceNode: AigcCanvasNode,
  targetNode: AigcCanvasNode,
): Record<string, unknown> {
  const data = downstreamDataFromSource(t, sourceNode, targetNode.type);
  const targetText = String(targetNode.data.text ?? "").trim();
  if (
    targetText &&
    sourceNode.type !== "prompt" &&
    Object.prototype.hasOwnProperty.call(data, "text")
  ) {
    const rest: Record<string, unknown> = { ...data };
    delete rest.text;
    return rest;
  }
  return data;
}

function edgeRoleForCanvasEdge(
  edge: AigcCanvasEdge,
  sourceNode: AigcCanvasNode | undefined,
) {
  if (sourceNode) return edgeRoleForSource(sourceNode);
  return String(edge.data?.role ?? "").trim();
}

function clearTargetDataForEdgeRole(role: string, targetType: string) {
  if (role === "style_template") {
    return {
      styleReferenceThumb: null,
      styleReferenceName: null,
      styleReferencePreviewUrl: null,
      styleTemplateId: null,
      styleTemplateUuid: null,
      effectTemplateUuids: null,
      effectId: null,
      effects: null,
      styleRuntimeMode: null,
      styleKeywords: null,
      styleDescription: null,
      styleSupplementalPrompt: null,
      visualDna: null,
      styleReferenceImages: null,
      aestheticProfileSnapshot: null,
      stylePreset: null,
      inputUpdated: true,
    };
  }
  if (
    role === "reference_image" ||
    role === "reference_video" ||
    role === "audio"
  ) {
    return {
      referenceThumb: null,
      referenceAssetName: null,
      referencePreviewUrl: null,
      ...(targetType === "image_generate" ? { imageMode: "blank" } : {}),
      ...(targetType === "video_generate"
        ? { activeVideoTab: null, videoMode: null }
        : {}),
      inputUpdated: true,
    };
  }
  return null;
}

const referenceRecordList = (value: unknown) =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object",
      )
    : [];

const trimValue = (value: unknown) => String(value ?? "").trim();

const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function sourceIdentityValues(sourceNode: AigcCanvasNode | undefined) {
  if (!sourceNode) return new Set<string>();
  const values = [
    sourceNode.id,
    sourceNode.data.assetId,
    sourceNode.data.assetPreviewUrl,
    sourceNode.data.referencePreviewUrl,
  ]
    .map(trimValue)
    .filter(Boolean);
  return new Set(values);
}

function referencedRecordIdentityValues(record: Record<string, unknown>) {
  return [
    record.sourceNodeId,
    record.id,
    record.previewUrl,
    record.url,
    record.assetPreviewUrl,
  ]
    .map(trimValue)
    .filter(Boolean);
}

function referencedRecordMatchesSource(
  record: Record<string, unknown>,
  sourceNode: AigcCanvasNode | undefined,
) {
  const sourceValues = sourceIdentityValues(sourceNode);
  if (sourceValues.size === 0) return false;
  return referencedRecordIdentityValues(record).some((value) =>
    sourceValues.has(value),
  );
}

function referenceRecordKind(record: Record<string, unknown>) {
  const kind = trimValue(record.kind ?? record.assetKind ?? record.type);
  const alias = trimValue(record.alias);
  if (kind === "text" || kind === "prompt" || alias.startsWith("文本")) {
    return "text";
  }
  return "image";
}

function nextReferenceAlias(
  record: Record<string, unknown>,
  counters: { image: number; text: number },
) {
  if (referenceRecordKind(record) === "text") {
    counters.text += 1;
    return `文本${counters.text}`;
  }
  counters.image += 1;
  return `图片${counters.image}`;
}

function aliasTokenPattern(alias: string) {
  return new RegExp(`@${escapeRegExp(alias)}\\b`, "g");
}

function cleanupReferenceMentionText(value: string) {
  return value
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]+([，。,.!?！？、；;：:])/g, "$1")
    .replace(/^[ \t]+|[ \t]+$/g, "");
}

function rewriteReferenceMentionText(
  value: string,
  changes: Array<{ from: string; to: string | null }>,
) {
  if (changes.length === 0) return value;
  let next = value;
  const placeholders = changes.map((_, index) => `__AIGC_REF_${index}__`);
  changes.forEach((change, index) => {
    if (!change.from) return;
    next = next.replace(aliasTokenPattern(change.from), placeholders[index]!);
  });
  changes.forEach((change, index) => {
    next = next
      .split(placeholders[index]!)
      .join(change.to ? `@${change.to}` : "");
  });
  return cleanupReferenceMentionText(next);
}

function cleanedReferencedAssetData(
  targetNode: AigcCanvasNode,
  sourceNode: AigcCanvasNode | undefined,
) {
  const existing = referenceRecordList(targetNode.data.referencedAssets);
  if (existing.length === 0) return null;

  const aliasChanges: Array<{ from: string; to: string | null }> = [];
  const counters = { image: 0, text: 0 };
  let changed = false;
  const nextReferencedAssets: Record<string, unknown>[] = [];

  existing.forEach((record) => {
    const oldAlias = trimValue(record.alias);
    if (referencedRecordMatchesSource(record, sourceNode)) {
      if (oldAlias) aliasChanges.push({ from: oldAlias, to: null });
      changed = true;
      return;
    }

    const nextAlias = nextReferenceAlias(record, counters);
    if (oldAlias && oldAlias !== nextAlias) {
      aliasChanges.push({ from: oldAlias, to: nextAlias });
      changed = true;
    }
    nextReferencedAssets.push(
      oldAlias === nextAlias ? record : { ...record, alias: nextAlias },
    );
  });

  const patch: Record<string, unknown> = {};
  (["text", "composerText"] as const).forEach((key) => {
    const value = targetNode.data[key];
    if (typeof value !== "string") return;
    const nextValue = rewriteReferenceMentionText(value, aliasChanges);
    if (nextValue !== value) {
      patch[key] = nextValue;
      changed = true;
    }
  });

  if (!changed) return null;
  return {
    ...patch,
    referencedAssets: nextReferencedAssets,
    inputUpdated: true,
  };
}

const nonEmptyValue = (value: unknown) => String(value ?? "").trim();

function shouldRepairTargetData(
  role: string,
  targetNode: AigcCanvasNode,
  targetData: Record<string, unknown>,
) {
  if (role === "style_template") {
    return Boolean(
      nonEmptyValue(targetData.styleReferencePreviewUrl) &&
        (!nonEmptyValue(targetNode.data.styleReferencePreviewUrl) ||
          !nonEmptyValue(targetNode.data.styleReferenceName)),
    );
  }
  if (
    role === "reference_image" ||
    role === "reference_video" ||
    role === "audio"
  ) {
    return Boolean(
      nonEmptyValue(targetData.referencePreviewUrl) &&
        (targetNode.data.referenceThumb !== true ||
          !nonEmptyValue(targetNode.data.referencePreviewUrl) ||
          !nonEmptyValue(targetNode.data.referenceAssetName) ||
          (targetNode.type === "image_generate" &&
            targetNode.data.imageMode !== "image_to_image")),
    );
  }
  return false;
}

export function reconcileCanvasConnectionData({
  canvas,
  t,
}: {
  canvas: AigcCanvas;
  t: Translate;
}): { canvas: AigcCanvas; changed: boolean } {
  if (canvas.edges.length === 0) return { canvas, changed: false };

  const nodesById = new Map(canvas.nodes.map((node) => [node.id, node]));
  let changed = false;

  for (const edge of canvas.edges) {
    const sourceNode = nodesById.get(edge.source);
    const targetNode = nodesById.get(edge.target);
    if (!sourceNode || !targetNode) continue;

    const role = edgeRoleForCanvasEdge(edge, sourceNode);
    const targetData = targetDataForPortConnection(t, sourceNode, targetNode);
    if (!shouldRepairTargetData(role, targetNode, targetData)) continue;

    changed = true;
    nodesById.set(targetNode.id, {
      ...targetNode,
      data: {
        ...targetNode.data,
        ...targetData,
      },
    });
  }

  if (!changed) return { canvas, changed: false };
  return {
    changed: true,
    canvas: {
      ...canvas,
      nodes: canvas.nodes.map((node) => nodesById.get(node.id) ?? node),
    },
  };
}

export function applyPortConnectionToCanvas({
  canvas,
  anchorNodeId,
  dropNodeId,
  side,
  t,
}: {
  canvas: AigcCanvas;
  anchorNodeId: string;
  dropNodeId: string;
  side: PortSide;
  t: Translate;
}): { canvas: AigcCanvas; selectedNodeId: string } | null {
  const anchorNode = canvas.nodes.find((node) => node.id === anchorNodeId);
  const dropNode = canvas.nodes.find((node) => node.id === dropNodeId);
  if (!anchorNode || !dropNode) return null;

  const endpoint = portConnectionEndpoint({ anchorNode, dropNode, side });
  if (!endpoint || !canConnectPortNodes(endpoint)) return null;

  const edge = createPortConnectionEdge(endpoint);
  const hasEdge = canvas.edges.some(
    (item) => item.source === edge.source && item.target === edge.target,
  );
  const targetData = targetDataForPortConnection(
    t,
    endpoint.sourceNode,
    endpoint.targetNode,
  );

  return {
    selectedNodeId: endpoint.targetNode.id,
    canvas: {
      ...canvas,
      nodes: canvas.nodes.map((node) =>
        node.id === endpoint.targetNode.id
          ? { ...node, data: { ...node.data, ...targetData } }
          : node,
      ),
      edges: hasEdge ? canvas.edges : [...canvas.edges, edge],
    },
  };
}

export function applyPortDisconnectionToCanvas({
  canvas,
  edgeId,
  t,
}: {
  canvas: AigcCanvas;
  edgeId: string;
  t: Translate;
}): { canvas: AigcCanvas; selectedNodeId: string } | null {
  const edge = canvas.edges.find((item) => item.id === edgeId);
  if (!edge) return null;

  const targetNode = canvas.nodes.find((node) => node.id === edge.target);
  if (!targetNode) return null;

  return {
    selectedNodeId: targetNode.id,
    canvas: cleanTargetDataForRemovedEdges({
      canvas,
      removedEdges: [edge],
      t,
    }),
  };
}

export function cleanTargetDataForRemovedEdges({
  canvas,
  removedEdges,
  t,
}: {
  canvas: AigcCanvas;
  removedEdges: AigcCanvasEdge[];
  t: Translate;
}): AigcCanvas {
  if (removedEdges.length === 0) return canvas;

  const removedEdgeIds = new Set(removedEdges.map((edge) => edge.id));
  const nextEdges = canvas.edges.filter((edge) => !removedEdgeIds.has(edge.id));
  const nodesById = new Map(canvas.nodes.map((node) => [node.id, node]));

  removedEdges.forEach((edge) => {
    const sourceNode = nodesById.get(edge.source);
    const targetNode = nodesById.get(edge.target);
    if (!targetNode) return;

    const role = edgeRoleForCanvasEdge(edge, sourceNode);
    const clearData = clearTargetDataForEdgeRole(role, targetNode.type);
    const replacementEdge = nextEdges.find((item) => {
      if (item.target !== targetNode.id) return false;
      const itemSource = nodesById.get(item.source);
      return edgeRoleForCanvasEdge(item, itemSource) === role;
    });
    const replacementSource = replacementEdge
      ? nodesById.get(replacementEdge.source)
      : undefined;
    const replacementData =
      replacementSource && role
        ? targetDataForPortConnection(t, replacementSource, targetNode)
        : {};
    const mentionData = cleanedReferencedAssetData(targetNode, sourceNode);

    if (!clearData && !replacementSource && !mentionData) return;
    nodesById.set(targetNode.id, {
      ...targetNode,
      data: {
        ...targetNode.data,
        ...(clearData ?? {}),
        ...replacementData,
        ...(mentionData ?? {}),
      },
    });
  });

  return {
    ...canvas,
    nodes: canvas.nodes.map((node) => nodesById.get(node.id) ?? node),
    edges: nextEdges,
  };
}
