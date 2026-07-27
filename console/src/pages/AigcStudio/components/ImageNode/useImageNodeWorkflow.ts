import { useCallback, type Dispatch, type SetStateAction } from "react";

import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import {
  DEFAULT_IMAGE_ASPECT_RATIO,
  DEFAULT_IMAGE_QUALITY,
  DEFAULT_IMAGE_RESOLUTION,
  PANORAMA_IMAGE_ASPECT_RATIO,
  imageModelDisplayName,
  imageModelForNode,
  isPanoramaImageNode,
} from "./imageNodeState";
import type {
  ImageCaptureMode,
  ImageNodeWorkflow,
  ImageSlashCommand,
  Translate,
} from "./types";

type UseImageNodeWorkflowArgs = {
  activeCanvas: AigcCanvas | null;
  commitCanvas: (canvas: AigcCanvas) => void;
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  modelOptions?: AigcCapabilityInfo[];
  t: Translate;
  createAssetPreviewUrl?: (file: File) => string;
  uploadAsset?: (file: File) => Promise<AigcAsset>;
  onAnnotateGeneratedImage?: (node: AigcCanvasNode) => void;
  getGeneratedImageResultsLayoutData?: (
    node: AigcCanvasNode,
  ) => Record<string, unknown>;
};

const connectNodes = (source: string, target: string): AigcCanvasEdge => ({
  id: `edge-${source}-${target}`,
  source,
  target,
  sourceHandle: "right",
  targetHandle: "left",
});

const captureModeCount: Record<ImageCaptureMode, number> = {
  current: 1,
  four: 4,
  twelve: 12,
};

const captureTitle = (mode: ImageCaptureMode) => {
  if (mode === "current") return "全景截图";
  if (mode === "four") return "全景截图组 (4张)";
  return "全景截图组 (12张)";
};

type CaptureFramePreset = {
  label: string;
  yaw: number;
  pitch: number;
  zoom: number;
};

const captureFramePresets = (mode: ImageCaptureMode): CaptureFramePreset[] => {
  if (mode === "current") {
    return [{ label: "全景截图-当前视角", yaw: 0, pitch: 0, zoom: 1 }];
  }
  if (mode === "four") {
    return [
      { label: "全景截图-前方", yaw: 0, pitch: 0, zoom: 1 },
      { label: "全景截图-左侧", yaw: 90, pitch: 0, zoom: 1 },
      { label: "全景截图-后方", yaw: 180, pitch: 0, zoom: 1 },
      { label: "全景截图-右侧", yaw: 270, pitch: 0, zoom: 1 },
    ];
  }
  return Array.from({ length: 12 }, (_, index) => {
    const yaw = index * 30;
    return {
      label: `全景截图-逆时针${yaw}°`,
      yaw,
      pitch: 0,
      zoom: 1,
    };
  });
};

const firstOutput = (node: AigcCanvasNode) =>
  Array.isArray(node.data.outputs) ? node.data.outputs[0] : undefined;

const outputValue = (output: unknown, key: string) =>
  output && typeof output === "object" && key in output
    ? (output as Record<string, unknown>)[key]
    : undefined;

const outputPath = (node: AigcCanvasNode) => {
  const output = firstOutput(node);
  return String(
    outputValue(output, "url") ?? outputValue(output, "path") ?? "",
  );
};

const outputName = (node: AigcCanvasNode) => {
  const output = firstOutput(node);
  return String(
    outputValue(output, "name") ??
      outputValue(output, "path") ??
      "generated-image",
  );
};

const captureFrames = (node: AigcCanvasNode) =>
  Array.isArray(node.data.captureFrames)
    ? (node.data.captureFrames as Array<Record<string, unknown>>)
    : [];

const selectedCaptureFrame = (node: AigcCanvasNode) => {
  const frames = captureFrames(node);
  const selectedId = String(node.data.selectedCaptureId ?? "");
  return (
    frames.find((frame) => String(frame.id ?? "") === selectedId) ?? frames[0]
  );
};

const captureGroupPreviewUrl = (node: AigcCanvasNode) => {
  const frame = selectedCaptureFrame(node);
  return String(
    frame?.assetPreviewUrl ?? node.data.sourceImageOutputPath ?? "",
  );
};

const captureGroupName = (node: AigcCanvasNode) => {
  const frame = selectedCaptureFrame(node);
  if (String(node.data.selectedCaptureId ?? "")) {
    return String(
      frame?.assetName ?? frame?.label ?? node.data.title ?? "截图组",
    );
  }
  return String(
    node.data.title ??
      node.data.sourceImageName ??
      node.data.assetName ??
      "全景截图组",
  );
};

const imageToolPresetData = (node: AigcCanvasNode) => {
  const presetData: Record<string, unknown> = {};
  (["stylePreset", "markPreset", "focusPreset"] as const).forEach((key) => {
    const value = node.data[key];
    if (typeof value === "string" && value.trim()) {
      presetData[key] = value;
    }
  });
  return presetData;
};

const captureFramesForMode = (
  mode: ImageCaptureMode,
  sourcePath: string,
  sourceName: string,
) =>
  captureFramePresets(mode).map((frame, index) => ({
    id: `${mode}-${index + 1}`,
    label: frame.label,
    yaw: frame.yaw,
    pitch: frame.pitch,
    zoom: frame.zoom,
    assetName: `${sourceName}-${frame.label}`,
    assetPreviewUrl: sourcePath,
  }));

const defaultAssetPreviewUrl = (file: File) => {
  try {
    if (typeof URL !== "undefined" && URL.createObjectURL) {
      return URL.createObjectURL(file);
    }
  } catch {
    return "";
  }
  return "";
};

const uploadedAssetPreviewUrl = (
  asset: AigcAsset | null,
  fallbackPreviewUrl: string,
) => String(asset?.url ?? asset?.path ?? fallbackPreviewUrl);

const uploadedAssetName = (asset: AigcAsset | null, file: File) =>
  String(asset?.name ?? file.name);

export function useImageNodeWorkflow({
  activeCanvas,
  commitCanvas,
  updateNodeData,
  setSelectedNodeId,
  modelOptions = [],
  t,
  createAssetPreviewUrl = defaultAssetPreviewUrl,
  uploadAsset,
  onAnnotateGeneratedImage,
  getGeneratedImageResultsLayoutData,
}: UseImageNodeWorkflowArgs): ImageNodeWorkflow {
  const handleImageUpload = useCallback(
    async (node: AigcCanvasNode, file?: File) => {
      if (!activeCanvas || !file) return;
      const localPreviewUrl = createAssetPreviewUrl(file);
      let asset: AigcAsset | null = null;
      try {
        asset = uploadAsset ? await uploadAsset(file) : null;
      } catch (error) {
        updateNodeData(node.id, {
          imageState: "failed",
          imageProgress: null,
          job_status: "failed",
          job_error:
            error instanceof Error
              ? error.message
              : t("aigcStudio.imageNode.uploadFailed", "参考图上传失败。"),
        });
        return;
      }

      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const sourceId = `image-source-${seed}`;
      const assetName = uploadedAssetName(asset, file);
      const assetPreviewUrl = uploadedAssetPreviewUrl(asset, localPreviewUrl);
      const sourcePosition = {
        x: Math.max(80, node.position.x),
        y: node.position.y + 4,
      };
      const targetPosition = {
        x: sourcePosition.x + 430,
        y: node.position.y + 22,
      };
      const sourceNode: AigcCanvasNode = {
        id: sourceId,
        type: "reference_asset",
        position: sourcePosition,
        data: {
          title: t("aigcStudio.imageNode.sources.image", "图片节点"),
          text: "",
          previewKind: "uploaded_source",
          assetKind: "image",
          assetName,
          assetPath: asset?.path,
          assetMimeType: asset?.mime_type || file.type,
          assetPreviewUrl,
          savedToAssets: Boolean(asset),
          uploadedAt: Date.now(),
        },
      };
      const updated = {
        ...activeCanvas,
        nodes: [
          ...activeCanvas.nodes.map((item) =>
            item.id === node.id
              ? {
                  ...item,
                  position: targetPosition,
                  data: {
                    ...item.data,
                    title: t("aigcStudio.imageNode.try.imageToImage", "图生图"),
                    imageMode: "image_to_image",
                    imageState: "editing",
                    imageProgress: null,
                    showTryOptions: false,
                    previewKind: null,
                    assetName: null,
                    assetPreviewUrl: null,
                    referenceThumb: true,
                    referenceAssetName: assetName,
                    referencePreviewUrl: assetPreviewUrl,
                    inputUpdated: true,
                    job_status: null,
                    job_error: null,
                    outputs: [],
                    composerPlaceholder: t(
                      "aigcStudio.imageNode.composer.imageToImage",
                      "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
                    ),
                  },
                }
              : item,
          ),
          sourceNode,
        ],
        edges: [...activeCanvas.edges, connectNodes(sourceId, node.id)],
      };
      commitCanvas(updated);
      setSelectedNodeId(node.id);
    },
    [
      activeCanvas,
      commitCanvas,
      createAssetPreviewUrl,
      setSelectedNodeId,
      t,
      updateNodeData,
      uploadAsset,
    ],
  );

  const handleImageToImageUpload = useCallback(
    async (node: AigcCanvasNode, file?: File) => {
      if (!activeCanvas || !file) return;
      const localPreviewUrl = createAssetPreviewUrl(file);
      let asset: AigcAsset | null = null;
      try {
        asset = uploadAsset ? await uploadAsset(file) : null;
      } catch (error) {
        updateNodeData(node.id, {
          imageState: "failed",
          imageProgress: null,
          job_status: "failed",
          job_error:
            error instanceof Error
              ? error.message
              : t("aigcStudio.imageNode.uploadFailed", "参考图上传失败。"),
        });
        return;
      }
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const sourceId = `image-source-${seed}`;
      const assetName = uploadedAssetName(asset, file);
      const assetPreviewUrl = uploadedAssetPreviewUrl(asset, localPreviewUrl);
      const sourcePosition = {
        x: Math.max(80, node.position.x),
        y: node.position.y + 4,
      };
      const targetPosition = {
        x: sourcePosition.x + 430,
        y: node.position.y + 22,
      };
      const sourceNode: AigcCanvasNode = {
        id: sourceId,
        type: "reference_asset",
        position: sourcePosition,
        data: {
          title: t("aigcStudio.imageNode.sources.image", "图片节点"),
          text: "",
          previewKind: "uploaded_source",
          assetKind: "image",
          assetName,
          assetPath: asset?.path,
          assetMimeType: asset?.mime_type || file.type,
          assetPreviewUrl,
          savedToAssets: Boolean(asset),
          uploadedAt: Date.now(),
        },
      };
      const updated = {
        ...activeCanvas,
        nodes: [
          ...activeCanvas.nodes.map((item) =>
            item.id === node.id
              ? {
                  ...item,
                  position: targetPosition,
                  data: {
                    ...item.data,
                    title: t("aigcStudio.imageNode.try.imageToImage", "图生图"),
                    text: "",
                    imageMode: "image_to_image",
                    imageState: "editing",
                    imageProgress: null,
                    showTryOptions: false,
                    referenceThumb: true,
                    referenceAssetName: assetName,
                    referencePreviewUrl: assetPreviewUrl,
                    inputUpdated: true,
                    job_status: null,
                    outputs: [],
                    composerPlaceholder: t(
                      "aigcStudio.imageNode.composer.imageToImage",
                      "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
                    ),
                  },
                }
              : item,
          ),
          sourceNode,
        ],
        edges: [...activeCanvas.edges, connectNodes(sourceId, node.id)],
      };
      commitCanvas(updated);
      setSelectedNodeId(node.id);
    },
    [
      activeCanvas,
      commitCanvas,
      createAssetPreviewUrl,
      setSelectedNodeId,
      t,
      updateNodeData,
      uploadAsset,
    ],
  );

  const handleImageUpscaleUpload = useCallback(
    async (node: AigcCanvasNode, file?: File) => {
      if (!activeCanvas || !file) return;
      const localPreviewUrl = createAssetPreviewUrl(file);
      let asset: AigcAsset | null = null;
      try {
        asset = uploadAsset ? await uploadAsset(file) : null;
      } catch (error) {
        updateNodeData(node.id, {
          imageState: "failed",
          imageProgress: null,
          job_status: "failed",
          job_error:
            error instanceof Error
              ? error.message
              : t("aigcStudio.imageNode.uploadFailed", "参考图上传失败。"),
        });
        return;
      }
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const sourceId = `upscale-source-${seed}`;
      const assetName = uploadedAssetName(asset, file);
      const assetPreviewUrl = uploadedAssetPreviewUrl(asset, localPreviewUrl);
      const sourcePosition = {
        x: Math.max(80, node.position.x),
        y: node.position.y + 4,
      };
      const targetPosition = {
        x: sourcePosition.x + 430,
        y: node.position.y + 10,
      };
      const sourceNode: AigcCanvasNode = {
        id: sourceId,
        type: "reference_asset",
        position: sourcePosition,
        data: {
          title: t("aigcStudio.imageNode.sources.image", "图片节点"),
          text: "",
          previewKind: "uploaded_source",
          assetKind: "image",
          assetName,
          assetPath: asset?.path,
          assetMimeType: asset?.mime_type || file.type,
          assetPreviewUrl,
          savedToAssets: Boolean(asset),
          uploadedAt: Date.now(),
        },
      };
      const updated = {
        ...activeCanvas,
        nodes: [
          ...activeCanvas.nodes.map((item) =>
            item.id === node.id
              ? {
                  ...item,
                  position: targetPosition,
                  data: {
                    ...item.data,
                    title: t("aigcStudio.imageNode.upscale.title", "高清"),
                    imageMode: "upscale",
                    imageState: "editing",
                    imageProgress: null,
                    showTryOptions: false,
                    referenceAssetName: assetName,
                    referencePreviewUrl: assetPreviewUrl,
                    inputUpdated: true,
                    job_status: null,
                    outputs: [],
                    upscaleProvider: "Topazlabs",
                    upscaleModel: t(
                      "aigcStudio.imageNode.upscale.model",
                      "通用",
                    ),
                    upscaleFactor: 2,
                  },
                }
              : item,
          ),
          sourceNode,
        ],
        edges: [...activeCanvas.edges, connectNodes(sourceId, node.id)],
      };
      commitCanvas(updated);
      setSelectedNodeId(node.id);
    },
    [
      activeCanvas,
      commitCanvas,
      createAssetPreviewUrl,
      setSelectedNodeId,
      t,
      updateNodeData,
      uploadAsset,
    ],
  );

  const handleImageComposerSubmit = useCallback(
    (node: AigcCanvasNode) => {
      const prompt = String(
        node.data.composerText ?? node.data.text ?? "",
      ).trim();
      const isPanorama = isPanoramaImageNode(node);
      const isUpscale = node.data.imageMode === "upscale";
      const imageModel = imageModelForNode(node, null, modelOptions);
      const nextData = {
        text: isUpscale ? "" : prompt || node.data.text || "",
        lastRunPrompt: isUpscale ? "" : prompt,
        imageState: "editing",
        imageProgress: null,
        job_status: null,
        outputs: [],
        modelLabel:
          imageModelDisplayName(imageModel?.model_name) ||
          (imageModel?.model_id ?? "Lib Navo Pro"),
        providerId: imageModel?.provider_id,
        modelId: imageModel?.model_id,
        modelCapability: imageModel?.capability,
        imageMode: isPanorama ? "panorama" : node.data.imageMode,
        panoramaMode: isPanorama,
        aspectRatio: isPanorama
          ? PANORAMA_IMAGE_ASPECT_RATIO
          : node.data.aspectRatio ?? DEFAULT_IMAGE_ASPECT_RATIO,
        imageQuality: node.data.imageQuality ?? DEFAULT_IMAGE_QUALITY,
        resolution: node.data.resolution ?? DEFAULT_IMAGE_RESOLUTION,
        imageCount: node.data.imageCount ?? 1,
      };
      updateNodeData(node.id, nextData);
      return {
        ...node,
        data: {
          ...node.data,
          ...nextData,
        },
      };
    },
    [modelOptions, updateNodeData],
  );

  const handleImageSlashCommand = useCallback(
    (node: AigcCanvasNode, command: ImageSlashCommand) => {
      updateNodeData(node.id, {
        composerText: command.description,
        slashCommand: command.title,
        text: command.description,
        imageState: "editing",
        imageProgress: null,
        showTryOptions: false,
        inputUpdated: true,
        job_status: null,
        outputs: [],
        slashReferenceError: null,
      });
    },
    [updateNodeData],
  );

  const handleImageCaptureGroup = useCallback(
    (node: AigcCanvasNode, mode: ImageCaptureMode) => {
      if (!activeCanvas) return;
      const captureCount = captureModeCount[mode];
      const sourcePath = outputPath(node);
      const sourceName = outputName(node);
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const captureNodeId = `image-capture-${mode}-${seed}`;
      const captureNode: AigcCanvasNode = {
        id: captureNodeId,
        type: "reference_asset",
        position: {
          x: node.position.x + 620,
          y: node.position.y,
        },
        data: {
          title: captureTitle(mode),
          text: "",
          previewKind: "image_capture_group",
          captureMode: mode,
          captureCount,
          captureFrames: captureFramesForMode(mode, sourcePath, sourceName),
          sourceImageNodeId: node.id,
          sourceImageOutputPath: sourcePath,
          sourceImageName: sourceName,
          participatesInGeneration: true,
          ...imageToolPresetData(node),
        },
      };

      commitCanvas({
        ...activeCanvas,
        nodes: [...activeCanvas.nodes, captureNode],
        edges: [...activeCanvas.edges, connectNodes(node.id, captureNodeId)],
      });
      setSelectedNodeId(captureNodeId);
    },
    [activeCanvas, commitCanvas, setSelectedNodeId],
  );

  const handleImageCaptureGroupSendToImage = useCallback(
    (node: AigcCanvasNode) => {
      if (!activeCanvas) return;
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const imageNodeId = `image-from-capture-${seed}`;
      const referenceAssetName = captureGroupName(node);
      const referencePreviewUrl = captureGroupPreviewUrl(node);
      const imageNode: AigcCanvasNode = {
        id: imageNodeId,
        type: "image_generate",
        position: {
          x: node.position.x + 620,
          y: node.position.y + 22,
        },
        data: {
          title: t("aigcStudio.imageNode.title", "图片节点"),
          text: t(
            "aigcStudio.imageNode.captureGroupToImagePrompt",
            "基于全景截图组继续生成/编辑。",
          ),
          composerText: "",
          imageMode: "image_to_image",
          imageState: "editing",
          imageProgress: null,
          job_status: null,
          outputs: [],
          showTryOptions: false,
          inputUpdated: true,
          referenceThumb: true,
          referenceAssetName,
          referencePreviewUrl,
          referenceCaptureGroupId: node.id,
          referenceCaptureCount: Number(node.data.captureCount ?? 0),
          aspectRatio: DEFAULT_IMAGE_ASPECT_RATIO,
          imageQuality: DEFAULT_IMAGE_QUALITY,
          resolution: DEFAULT_IMAGE_RESOLUTION,
          imageCount: 1,
          ...imageToolPresetData(node),
        },
      };

      commitCanvas({
        ...activeCanvas,
        nodes: [...activeCanvas.nodes, imageNode],
        edges: [...activeCanvas.edges, connectNodes(node.id, imageNodeId)],
      });
      setSelectedNodeId(imageNodeId);
    },
    [activeCanvas, commitCanvas, setSelectedNodeId, t],
  );

  const handleImageCaptureGroupSelect = useCallback(
    (node: AigcCanvasNode, captureId: string) => {
      const frame = captureFrames(node).find(
        (item) => String(item.id ?? "") === captureId,
      );
      if (!frame) return;
      updateNodeData(node.id, {
        selectedCaptureId: captureId,
        assetId: frame.assetId,
        assetName: frame.assetName ?? frame.label,
        assetPath: frame.assetPath,
        assetMimeType: frame.assetMimeType,
        assetPreviewUrl: frame.assetPreviewUrl,
        referenceAssetId: frame.assetId,
        referenceAssetName: frame.assetName ?? frame.label,
        referencePreviewUrl: frame.assetPreviewUrl,
      });
    },
    [updateNodeData],
  );

  const handleGeneratedImageSendToImage = useCallback(
    (node: AigcCanvasNode) => {
      if (!activeCanvas) return;
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const imageNodeId = `image-from-result-${seed}`;
      const referenceAssetName = outputName(node);
      const referencePreviewUrl = outputPath(node);
      const imageNode: AigcCanvasNode = {
        id: imageNodeId,
        type: "image_generate",
        position: {
          x: node.position.x + 620,
          y: node.position.y + 22,
        },
        data: {
          title: t("aigcStudio.imageNode.title", "图片节点"),
          text: t(
            "aigcStudio.imageNode.generatedImageToImagePrompt",
            "基于生成图片继续生成/编辑。",
          ),
          composerText: "",
          imageMode: "image_to_image",
          imageState: "editing",
          imageProgress: null,
          job_status: null,
          outputs: [],
          showTryOptions: false,
          inputUpdated: true,
          referenceThumb: true,
          referenceAssetName,
          referencePreviewUrl,
          referenceImageNodeId: node.id,
          aspectRatio: DEFAULT_IMAGE_ASPECT_RATIO,
          imageQuality: DEFAULT_IMAGE_QUALITY,
          resolution: DEFAULT_IMAGE_RESOLUTION,
          imageCount: 1,
          ...imageToolPresetData(node),
        },
      };

      commitCanvas({
        ...activeCanvas,
        nodes: [...activeCanvas.nodes, imageNode],
        edges: [...activeCanvas.edges, connectNodes(node.id, imageNodeId)],
      });
      setSelectedNodeId(imageNodeId);
    },
    [activeCanvas, commitCanvas, setSelectedNodeId, t],
  );

  const handleGeneratedImageAnnotate = useCallback(
    (node: AigcCanvasNode) => {
      onAnnotateGeneratedImage?.(node);
    },
    [onAnnotateGeneratedImage],
  );

  const handleGeneratedImageSetPrimary = useCallback(
    (node: AigcCanvasNode, outputId: string) => {
      updateNodeData(node.id, {
        primaryOutputId: outputId,
        primaryOutputIndex: null,
      });
    },
    [updateNodeData],
  );

  const handleGeneratedImageToggleResults = useCallback(
    (node: AigcCanvasNode, expanded: boolean) => {
      const layoutData = expanded
        ? getGeneratedImageResultsLayoutData?.(node) ?? {}
        : {
            imageResultsPrimaryWidth: null,
            imageResultsGalleryWidth: null,
            imageResultsGalleryHeight: null,
            imageResultsGalleryLeft: null,
            imageResultsGalleryTop: null,
            imageResultsGalleryColumns: null,
            imageResultsGalleryPlacement: null,
          };
      updateNodeData(node.id, {
        imageResultsExpanded: expanded,
        ...layoutData,
      });
    },
    [getGeneratedImageResultsLayoutData, updateNodeData],
  );

  return {
    handleImageUpload,
    handleImageToImageUpload,
    handleImageUpscaleUpload,
    handleImageComposerSubmit,
    handleImageCaptureGroup,
    handleGeneratedImageSendToImage,
    handleGeneratedImageAnnotate,
    handleGeneratedImageSetPrimary,
    handleGeneratedImageToggleResults,
    handleImageCaptureGroupSendToImage,
    handleImageCaptureGroupSelect,
    handleImageSlashCommand,
  };
}
