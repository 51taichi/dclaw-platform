import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";
import {
  createAssetNodeFromUpload,
  type CanvasPoint,
} from "./canvasAssetFactory";
import type { CanvasAssetRecord, Translate } from "./canvasNodeUtils";

export function filterCanvasAssetFiles(files: FileList | File[]) {
  return Array.from(files).filter((file) =>
    /^(image|video|audio)\//.test(file.type),
  );
}

export function buildUploadedAssetNodes({
  t,
  files,
  assets,
  position,
  nodeCount,
}: {
  t: Translate;
  files: File[];
  assets: AigcAsset[];
  position: CanvasPoint;
  nodeCount: number;
}) {
  return files.map((file, index) =>
    createAssetNodeFromUpload(
      t,
      assets[index]!,
      file,
      index,
      position,
      nodeCount,
    ),
  );
}

export function defaultAssetNodePosition(nodeCount: number): CanvasPoint {
  return {
    x: 120 + (nodeCount % 4) * 260,
    y: 130 + Math.floor(nodeCount / 4) * 180,
  };
}

export function createAssetNodeFromRecord({
  record,
  nodeCount,
}: {
  record: CanvasAssetRecord;
  nodeCount: number;
}): AigcCanvasNode {
  return {
    id: `asset-node-${Date.now().toString(36)}-${nodeCount + 1}`,
    type: "reference_asset",
    position: defaultAssetNodePosition(nodeCount),
    data: {
      title: record.title,
      text: record.text,
      previewKind: record.previewKind ?? "uploaded_source",
      assetPreviewUrl: record.assetPreviewUrl,
      assetName: record.title,
    },
  };
}

export function appendCanvasNodes(
  canvas: AigcCanvas,
  nodes: AigcCanvasNode[],
): AigcCanvas {
  return {
    ...canvas,
    nodes: [...canvas.nodes, ...nodes],
  };
}

export function replaceSourceImageReferences({
  canvas,
  sourceNodeId,
  assetName,
  assetPreviewUrl,
}: {
  canvas: AigcCanvas;
  sourceNodeId: string;
  assetName: string;
  assetPreviewUrl: string;
}): AigcCanvas {
  const targetIds = canvas.edges
    .filter((edge) => edge.source === sourceNodeId)
    .map((edge) => edge.target);
  return {
    ...canvas,
    nodes: canvas.nodes.map((item) => {
      if (item.id === sourceNodeId) {
        return {
          ...item,
          data: {
            ...item.data,
            assetName,
            assetPreviewUrl,
          },
        };
      }
      if (targetIds.includes(item.id)) {
        return {
          ...item,
          data: {
            ...item.data,
            referenceAssetName: assetName,
            referencePreviewUrl: assetPreviewUrl,
            inputUpdated: true,
          },
        };
      }
      return item;
    }),
  };
}
