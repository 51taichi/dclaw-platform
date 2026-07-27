import { useCallback, useState } from "react";

import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import { dataUrlToFile } from "./directorStageAssetBridge";
import {
  directorStageAttributionsForProject,
  directorStageCapturesFromNode,
  type DirectorStageCapture,
  type DirectorStageModelAsset,
  type DirectorStageObjectKind,
  type DirectorStageProject,
} from "./directorStageTypes";
import type {
  DirectorStageCaptureBatchResult,
  DirectorStageCapturePayload,
  DirectorStageCaptureResult,
  DirectorStageModelUploadResult,
  DirectorStageWorkflow,
} from "./types";
import type { Translate } from "../ImageNode/types";

type UseDirectorStageWorkflowArgs = {
  activeCanvas: AigcCanvas | null;
  commitCanvas: (canvas: AigcCanvas) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  uploadAsset: (file: File) => Promise<AigcAsset>;
  t: Translate;
};

export const DIRECTOR_STAGE_MODEL_MAX_BYTES = 100 * 1024 * 1024;

const connectNodes = (source: string, target: string): AigcCanvasEdge => ({
  id: `edge-${source}-${target}`,
  source,
  target,
  sourceHandle: "right",
  targetHandle: "left",
});

const assetPreviewUrl = (asset: AigcAsset) =>
  String(asset.url ?? asset.path ?? "").trim();

const modelNameFromFile = (fileName: string) =>
  fileName.replace(/\.glb$/i, "").trim() || "自定义模型";

function validateDirectorStageModel(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".glb")) {
    return "导演台当前仅支持单文件 GLB 模型";
  }
  if (!file.size) return "模型文件不能为空";
  if (file.size > DIRECTOR_STAGE_MODEL_MAX_BYTES) {
    return "模型文件不能超过 100 MB";
  }
  return null;
}

function createDirectorStageModelAsset(
  asset: AigcAsset,
  file: File,
  kind: DirectorStageObjectKind,
): DirectorStageModelAsset {
  const url = assetPreviewUrl(asset);
  if (!url) throw new Error("模型资产缺少可访问地址");
  const createdAt = Date.parse(asset.created_at);
  return {
    id: `uploaded-model-${asset.id}`,
    assetId: asset.id,
    kind,
    name: modelNameFromFile(asset.name || file.name),
    fileName: asset.name || file.name,
    url,
    assetPath: asset.path,
    mimeType: asset.mime_type,
    size: file.size,
    createdAt: Number.isFinite(createdAt) ? createdAt : Date.now(),
  };
}

const captureNodeTitle = (t: Translate) =>
  t("aigcStudio.directorStage.captureNodeTitle", "导演台截图");

const captureGroupTitle = (t: Translate) =>
  t("aigcStudio.directorStage.captureGroupTitle", "导演台截图组");

function createCaptureRecord(asset: AigcAsset): DirectorStageCapture {
  return {
    id: `director-stage-capture-${asset.id}`,
    assetId: asset.id,
    assetPath: asset.path,
    createdAt: Date.now(),
    mimeType: asset.mime_type,
    name: asset.name,
    previewUrl: assetPreviewUrl(asset),
  };
}

function createCaptureReferenceNode({
  asset,
  capture,
  node,
  nodeCount,
  placementIndex,
  t,
}: {
  asset: AigcAsset;
  capture: DirectorStageCapture;
  node: AigcCanvasNode;
  nodeCount: number;
  placementIndex: number;
  t: Translate;
}): AigcCanvasNode {
  const seed = `${Date.now().toString(36)}-${nodeCount + placementIndex + 1}`;
  return {
    id: `director-stage-capture-${seed}`,
    type: "reference_asset",
    position: {
      x: node.position.x + 430,
      y: node.position.y + 24 + placementIndex * 320,
    },
    data: {
      title: captureNodeTitle(t),
      text: "",
      previewKind: "uploaded_source",
      assetKind: "image",
      assetName: capture.name,
      assetPath: asset.path,
      assetMimeType: asset.mime_type,
      assetPreviewUrl: capture.previewUrl,
      savedToAssets: true,
      sourceDirectorStageNodeId: node.id,
      uploadedAt: capture.createdAt,
    },
  };
}

function createCaptureGroupNode({
  assets,
  captures,
  node,
  placementIndex,
  project,
  t,
}: {
  assets: AigcAsset[];
  captures: DirectorStageCapture[];
  node: AigcCanvasNode;
  placementIndex: number;
  project: DirectorStageProject;
  t: Translate;
}): AigcCanvasNode {
  const seed = `${Date.now().toString(36)}-${captures.length}`;
  const firstAsset = assets[0];
  const firstCapture = captures[0];
  return {
    id: `director-stage-capture-group-${seed}`,
    type: "reference_asset",
    position: {
      x: node.position.x + 430,
      y: node.position.y + 24 + placementIndex * 320,
    },
    data: {
      title: captureGroupTitle(t),
      text: "",
      previewKind: "image_capture_group",
      captureMode: "director_stage",
      captureCount: captures.length,
      captureFrames: captures.map((capture, index) => {
        const camera = project.cameras[index];
        return {
          id: capture.id,
          label: camera?.name ?? capture.name.replace(/\.[^.]+$/, ""),
          assetId: capture.assetId,
          assetName: capture.name,
          assetPath: capture.assetPath,
          assetMimeType: capture.mimeType,
          assetPreviewUrl: capture.previewUrl,
          cameraId: camera?.id,
          position: camera?.position,
          target: camera?.target,
          fov: camera?.fov,
        };
      }),
      selectedCaptureId: firstCapture?.id,
      assetKind: "image",
      assetId: firstAsset?.id,
      assetName: firstCapture?.name,
      assetPath: firstCapture?.assetPath,
      assetMimeType: firstCapture?.mimeType,
      assetPreviewUrl: firstCapture?.previewUrl,
      referenceAssetId: firstAsset?.id,
      referenceAssetName: firstCapture?.name,
      referencePreviewUrl: firstCapture?.previewUrl,
      savedToAssets: true,
      participatesInGeneration: true,
      sourceDirectorStageNodeId: node.id,
      uploadedAt: firstCapture?.createdAt,
    },
  };
}

function canvasWithStageCaptures({
  activeCanvas,
  assets,
  captures,
  node,
  project,
  t,
  grouped = false,
}: {
  activeCanvas: AigcCanvas;
  assets: AigcAsset[];
  captures: DirectorStageCapture[];
  node: AigcCanvasNode;
  project: DirectorStageProject;
  t: Translate;
  grouped?: boolean;
}) {
  const existingPlacementUnits = activeCanvas.nodes.reduce(
    (count, item) =>
      item.data.sourceDirectorStageNodeId === node.id
        ? count + (item.data.previewKind === "image_capture_group" ? 2 : 1)
        : count,
    0,
  );
  const captureNodes = grouped
    ? [
        createCaptureGroupNode({
          assets,
          captures,
          node,
          placementIndex: existingPlacementUnits,
          project,
          t,
        }),
      ]
    : captures.map((capture, index) =>
        createCaptureReferenceNode({
          asset: assets[index]!,
          capture,
          node,
          nodeCount: activeCanvas.nodes.length,
          placementIndex: existingPlacementUnits + index,
          t,
        }),
      );
  const nextCaptures = [...directorStageCapturesFromNode(node), ...captures];
  const latestAsset = assets[assets.length - 1];
  const latestCapture = captures[captures.length - 1];
  const updatedStageNode: AigcCanvasNode = {
    ...node,
    data: {
      ...node.data,
      directorStageCaptures: nextCaptures,
      directorStageError: null,
      directorStageProject: project,
      modelAttributions: directorStageAttributionsForProject(project),
      previewAssetId: latestAsset?.id,
      previewUrl: latestCapture?.previewUrl,
    },
  };

  return {
    canvas: {
      ...activeCanvas,
      nodes: [
        ...activeCanvas.nodes.map((item) =>
          item.id === node.id ? updatedStageNode : item,
        ),
        ...captureNodes,
      ],
      edges: [
        ...activeCanvas.edges,
        ...captureNodes.map((captureNode) =>
          connectNodes(node.id, captureNode.id),
        ),
      ],
    },
    captureNodes,
  };
}

export function useDirectorStageWorkflow({
  activeCanvas,
  commitCanvas,
  setSelectedNodeId,
  updateNodeData,
  uploadAsset,
  t,
}: UseDirectorStageWorkflowArgs): DirectorStageWorkflow {
  const [openNodeId, setOpenNodeId] = useState<string | null>(null);

  const handleOpenStage = useCallback((node: AigcCanvasNode) => {
    setOpenNodeId(node.id);
  }, []);

  const handleCloseStage = useCallback(() => {
    setOpenNodeId(null);
  }, []);

  const handleSaveProject = useCallback(
    (node: AigcCanvasNode, project: DirectorStageProject) => {
      updateNodeData(node.id, {
        directorStageError: null,
        directorStageProject: project,
        modelAttributions: directorStageAttributionsForProject(project),
      });
    },
    [updateNodeData],
  );

  const handleUploadModel = useCallback(
    async (
      node: AigcCanvasNode,
      file: File,
      kind: DirectorStageObjectKind,
    ): Promise<DirectorStageModelUploadResult> => {
      const validationError = validateDirectorStageModel(file);
      if (validationError) {
        updateNodeData(node.id, { directorStageError: validationError });
        return { ok: false, error: validationError };
      }
      try {
        const asset = await uploadAsset(file);
        const model = createDirectorStageModelAsset(asset, file, kind);
        updateNodeData(node.id, { directorStageError: null });
        return { ok: true, model };
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : t("aigcStudio.directorStage.modelUploadFailed", "模型上传失败");
        updateNodeData(node.id, { directorStageError: errorMessage });
        return { ok: false, error: errorMessage };
      }
    },
    [t, updateNodeData, uploadAsset],
  );

  const handleCaptureBatch = useCallback(
    async (
      node: AigcCanvasNode,
      payloads: DirectorStageCapturePayload[],
    ): Promise<DirectorStageCaptureBatchResult> => {
      if (!activeCanvas) {
        return {
          ok: false,
          error: t("aigcStudio.directorStage.noCanvas", "当前画布不可用"),
        };
      }
      if (!payloads.length) {
        return {
          ok: false,
          error: t("aigcStudio.directorStage.noCameras", "当前没有可截图机位"),
        };
      }
      const project = payloads[0]!.project;
      try {
        const files = await Promise.all(
          payloads.map((payload) =>
            dataUrlToFile(payload.dataUrl, payload.fileName),
          ),
        );
        const assets = await Promise.all(
          files.map((file) => uploadAsset(file)),
        );
        const captures = assets.map(createCaptureRecord);
        const { canvas, captureNodes } = canvasWithStageCaptures({
          activeCanvas,
          assets,
          captures,
          node,
          project,
          t,
          grouped: true,
        });
        commitCanvas(canvas);
        setSelectedNodeId(captureNodes[captureNodes.length - 1]?.id ?? node.id);
        return {
          ok: true,
          captures,
        };
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : t("aigcStudio.directorStage.captureFailed", "机位截图上传失败");
        updateNodeData(node.id, {
          directorStageError: errorMessage,
          directorStageProject: project,
          modelAttributions: directorStageAttributionsForProject(project),
        });
        return {
          ok: false,
          error: errorMessage,
        };
      }
    },
    [
      activeCanvas,
      commitCanvas,
      setSelectedNodeId,
      t,
      updateNodeData,
      uploadAsset,
    ],
  );

  const handleCapture = useCallback(
    async (
      node: AigcCanvasNode,
      payload: DirectorStageCapturePayload,
    ): Promise<DirectorStageCaptureResult> => {
      if (!activeCanvas) {
        return {
          ok: false,
          error: t("aigcStudio.directorStage.noCanvas", "当前画布不可用"),
        };
      }
      try {
        const file = await dataUrlToFile(payload.dataUrl, payload.fileName);
        const asset = await uploadAsset(file);
        const capture = createCaptureRecord(asset);
        const { canvas, captureNodes } = canvasWithStageCaptures({
          activeCanvas,
          assets: [asset],
          captures: [capture],
          node,
          project: payload.project,
          t,
        });
        commitCanvas(canvas);
        setSelectedNodeId(captureNodes[0]?.id ?? node.id);
        return { ok: true, capture };
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : t("aigcStudio.directorStage.captureFailed", "机位截图上传失败");
        updateNodeData(node.id, {
          directorStageError: errorMessage,
          directorStageProject: payload.project,
          modelAttributions: directorStageAttributionsForProject(
            payload.project,
          ),
        });
        return { ok: false, error: errorMessage };
      }
    },
    [
      activeCanvas,
      commitCanvas,
      setSelectedNodeId,
      t,
      updateNodeData,
      uploadAsset,
    ],
  );

  return {
    openNodeId,
    handleOpenStage,
    handleCloseStage,
    handleSaveProject,
    handleCapture,
    handleCaptureBatch,
    handleUploadModel,
  };
}
