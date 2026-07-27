import { useCallback, type Dispatch, type SetStateAction } from "react";

import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { modelForNode } from "../../nodeModelSelection";
import type {
  Translate,
  VideoNodeWorkflow,
  VideoReferenceMode,
  VideoResultAction,
  VideoTryAction,
} from "./types";

type UseVideoNodeWorkflowArgs = {
  activeCanvas: AigcCanvas | null;
  commitCanvas: (canvas: AigcCanvas) => void;
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  modelOptions?: AigcCapabilityInfo[];
  t: Translate;
  createAssetPreviewUrl?: (file: File) => string;
  uploadAsset?: (file: File) => Promise<AigcAsset>;
  onRunNode?: (node: AigcCanvasNode) => void | Promise<void>;
};

const connectNodes = (source: string, target: string): AigcCanvasEdge => ({
  id: `edge-${source}-${target}`,
  source,
  target,
  sourceHandle: "right",
  targetHandle: "left",
});

const firstVideoOutput = (node: AigcCanvasNode) =>
  Array.isArray(node.data.outputs)
    ? node.data.outputs.find(
        (output) =>
          Boolean(output) &&
          typeof output === "object" &&
          String((output as Record<string, unknown>).kind ?? "video") ===
            "video",
      )
    : undefined;

const outputValue = (output: unknown, key: string) =>
  output && typeof output === "object" && key in output
    ? (output as Record<string, unknown>)[key]
    : undefined;

const textValue = (value: unknown) =>
  typeof value === "string" && value.trim() ? value.trim() : undefined;

const videoOutputPath = (node: AigcCanvasNode) => {
  const output = firstVideoOutput(node);
  return String(
    outputValue(output, "url") ??
      outputValue(output, "path") ??
      textValue(node.data.videoPreviewUrl) ??
      textValue(node.data.assetPreviewUrl) ??
      textValue(node.data.referencePreviewUrl) ??
      "",
  );
};

const videoOutputName = (node: AigcCanvasNode) => {
  const output = firstVideoOutput(node);
  return String(
    outputValue(output, "name") ??
      outputValue(output, "path") ??
      textValue(node.data.videoAssetName) ??
      textValue(node.data.assetName) ??
      textValue(node.data.referenceAssetName) ??
      "generated-video.mp4",
  );
};

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

const assetKindFromFile = (file: File) => {
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  if (file.type.startsWith("image/")) return "image";
  return "file";
};

const referenceUploadLimit = (mode: VideoReferenceMode) => {
  if (mode === "image_to_video") return 1;
  if (mode === "first_frame") return 2;
  if (mode === "image_reference") return 4;
  return 9;
};

const referenceModeVideoMode = (mode: VideoReferenceMode) =>
  mode === "first_frame" ? "first_last_frames" : mode;

const referenceModePrompt = (t: Translate, mode: VideoReferenceMode) => {
  if (mode === "all_reference") {
    return t(
      "aigcStudio.videoNode.composer.allReference",
      "结合图片、视频、音频等参考素材生成视频。",
    );
  }
  if (mode === "image_to_video") {
    return t(
      "aigcStudio.videoNode.composer.imageToVideo",
      "基于参考图与描述生成视频。",
    );
  }
  if (mode === "image_reference") {
    return t(
      "aigcStudio.videoNode.composer.imageReference",
      "参考多张图片与描述生成视频。",
    );
  }
  return t(
    "aigcStudio.videoNode.composer.firstLast",
    "根据首尾帧与描述生成过渡自然的视频。",
  );
};

const referenceSourceLabel = (
  t: Translate,
  mode: VideoReferenceMode,
  file: File,
  index: number,
) => {
  if (mode === "first_frame") {
    return index === 0
      ? t("aigcStudio.videoNode.sources.firstFrame", "首帧")
      : t("aigcStudio.videoNode.sources.lastFrame", "尾帧");
  }
  if (mode === "image_to_video") {
    return t("aigcStudio.videoNode.sources.referenceImage", "参考图");
  }
  if (mode === "image_reference") {
    return `${t("aigcStudio.videoNode.sources.imageReference", "图片参考")} ${
      index + 1
    }`;
  }
  const kind = assetKindFromFile(file);
  if (kind === "video") {
    return t("aigcStudio.videoNode.sources.videoReference", "视频参考");
  }
  if (kind === "audio") {
    return t("aigcStudio.videoNode.sources.audioReference", "音频参考");
  }
  return t("aigcStudio.videoNode.sources.imageReference", "图片参考");
};

type VideoDerivativeAction = Exclude<
  VideoResultAction,
  "analyze" | "extract_audio"
>;

type VideoDerivativeConfig = {
  idPrefix: string;
  title: string;
  text: string;
  videoMode: string;
  videoResolution?: string;
  extraData?: Record<string, unknown>;
};

const videoDerivativeConfig = (
  t: Translate,
  action: VideoDerivativeAction,
): VideoDerivativeConfig => {
  if (action === "edit") {
    return {
      idPrefix: "video-edit",
      title: t("aigcStudio.videoNode.result.editTitle", "视频剪辑"),
      text: t(
        "aigcStudio.videoNode.result.editPrompt",
        "基于生成视频继续剪辑片段、节奏和转场。",
      ),
      videoMode: "video_edit",
    };
  }
  if (action === "crop") {
    return {
      idPrefix: "video-crop",
      title: t("aigcStudio.videoNode.result.cropTitle", "视频裁剪"),
      text: t(
        "aigcStudio.videoNode.result.cropPrompt",
        "裁剪生成视频画面并调整构图。",
      ),
      videoMode: "video_crop",
      extraData: { cropMode: "free" },
    };
  }
  if (action === "remove_subtitles") {
    return {
      idPrefix: "video-subtitle-removal",
      title: t(
        "aigcStudio.videoNode.result.subtitleRemovalTitle",
        "智能去字幕",
      ),
      text: t(
        "aigcStudio.videoNode.result.subtitleRemovalPrompt",
        "移除视频中的字幕与文字覆盖。",
      ),
      videoMode: "remove_subtitles",
    };
  }
  return {
    idPrefix: "video-upscale",
    title: t("aigcStudio.videoNode.result.upscaleTitle", "视频高清"),
    text: t(
      "aigcStudio.videoNode.result.upscalePrompt",
      "对生成视频进行高清增强。",
    ),
    videoMode: "video_upscale",
    videoResolution: "1080P",
  };
};

const downstreamResultActionCount = (
  canvas: AigcCanvas,
  sourceNodeId: string,
) =>
  canvas.nodes.filter(
    (node) =>
      String(
        node.data.sourceVideoNodeId ?? node.data.referenceVideoNodeId ?? "",
      ) === sourceNodeId,
  ).length;

export function useVideoNodeWorkflow({
  activeCanvas,
  commitCanvas,
  updateNodeData,
  setSelectedNodeId,
  modelOptions = [],
  t,
  createAssetPreviewUrl = defaultAssetPreviewUrl,
  uploadAsset,
  onRunNode,
}: UseVideoNodeWorkflowArgs): VideoNodeWorkflow {
  const prepareVideoReferenceFiles = useCallback(
    async (node: AigcCanvasNode, files: File[]) => {
      try {
        return await Promise.all(
          files.map(async (file) => {
            const localPreviewUrl = createAssetPreviewUrl(file);
            const asset = uploadAsset ? await uploadAsset(file) : null;
            return {
              file,
              asset,
              assetKind: String(asset?.kind ?? assetKindFromFile(file)),
              assetName: uploadedAssetName(asset, file),
              assetPath: asset?.path,
              assetMimeType: asset?.mime_type || file.type,
              assetPreviewUrl: uploadedAssetPreviewUrl(asset, localPreviewUrl),
              savedToAssets: Boolean(asset),
            };
          }),
        );
      } catch (error) {
        updateNodeData(node.id, {
          videoState: "failed",
          videoProgress: null,
          job_status: "failed",
          job_error:
            error instanceof Error
              ? error.message
              : t("aigcStudio.videoNode.uploadFailed", "参考素材上传失败。"),
        });
        return null;
      }
    },
    [createAssetPreviewUrl, t, updateNodeData, uploadAsset],
  );

  const handleVideoUpload = useCallback(
    async (node: AigcCanvasNode, file?: File) => {
      if (!file) return;
      const prepared = await prepareVideoReferenceFiles(node, [file]);
      const source = prepared?.[0];
      if (!source) return;
      updateNodeData(node.id, {
        videoAssetName: source.assetName,
        videoPreviewUrl: source.assetPreviewUrl,
        videoAssetPath: source.assetPath,
        videoMimeType: source.assetMimeType,
        savedToAssets: source.savedToAssets,
        previewKind: "uploaded_video",
        showTryOptions: false,
      });
    },
    [prepareVideoReferenceFiles, updateNodeData],
  );

  const handleVideoTryUpload = useCallback(
    async (
      node: AigcCanvasNode,
      action: VideoTryAction,
      files?: FileList | null,
    ) => {
      if (!activeCanvas || !files?.length) return;
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const pickedFiles = Array.from(files).slice(
        0,
        action === "first_last_frames" ? 2 : 1,
      );
      const preparedFiles = await prepareVideoReferenceFiles(node, pickedFiles);
      if (!preparedFiles) return;
      const selectedVideoModel = modelForNode(
        modelOptions,
        node,
        "text_to_video",
      );
      const currentModelLabel =
        selectedVideoModel?.model_name ?? selectedVideoModel?.model_id;
      const sourceNodes: AigcCanvasNode[] = preparedFiles.map((source, index) => {
        const label =
          action === "first_last_frames"
            ? index === 0
              ? t("aigcStudio.videoNode.sources.firstFrame", "首帧")
              : t("aigcStudio.videoNode.sources.lastFrame", "尾帧")
            : t("aigcStudio.videoNode.sources.firstFrame", "首帧");
        return {
          id: `video-source-${seed}-${index + 1}`,
          type: "reference_asset",
          position: {
            x: Math.max(80, node.position.x - 520),
            y: node.position.y + index * 260,
          },
          data: {
            title: label,
            text: "",
            previewKind: "uploaded_source",
            assetShape: "wide",
            assetKind: source.assetKind,
            assetName: source.assetName,
            assetPath: source.assetPath,
            assetMimeType: source.assetMimeType,
            assetPreviewUrl: source.assetPreviewUrl,
            savedToAssets: source.savedToAssets,
            uploadedAt: Date.now(),
          },
        };
      });
      const primary = sourceNodes[0];
      const videoReferenceAssets = sourceNodes.map((source, index) => ({
        id: source.id,
        label: String(source.data.title ?? ""),
        name: String(source.data.assetName ?? ""),
        kind: String(source.data.assetKind ?? "image"),
        previewUrl: String(source.data.assetPreviewUrl ?? ""),
        assetPath: source.data.assetPath,
        mimeType: source.data.assetMimeType,
        role: action === "first_last_frames" && index === 1 ? "last_frame" : "first_frame",
      }));
      const targetPosition = {
        x: Math.max(
          node.position.x,
          (primary?.position.x ?? node.position.x) + 560,
        ),
        y: node.position.y,
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
                    title: t("aigcStudio.videoNode.title", "视频节点"),
                    text:
                      action === "first_last_frames"
                        ? t(
                            "aigcStudio.videoNode.composer.firstLast",
                            "根据首尾帧与描述生成过渡自然的视频。",
                          )
                        : t(
                            "aigcStudio.videoNode.composer.firstFrame",
                            "以当前图为首帧生成视频。",
                          ),
                    videoMode:
                      action === "first_last_frames"
                        ? "first_last_frames"
                        : "first_frame",
                    activeVideoTab:
                      action === "first_last_frames"
                        ? "first_frame"
                        : "first_frame",
                    showTryOptions: false,
                    referenceThumb: true,
                    referenceAssetName: preparedFiles
                      .map((source) => source.assetName)
                      .join(", "),
                    referencePreviewUrl: primary?.data.assetPreviewUrl,
                    referenceCount: pickedFiles.length,
                    videoReferenceAssets,
                    inputUpdated: true,
                    videoModel: currentModelLabel,
                    modelLabel: currentModelLabel,
                    providerId: selectedVideoModel?.provider_id,
                    modelId: selectedVideoModel?.model_id,
                    modelCapability: selectedVideoModel?.capability,
                    aspectRatio: item.data.aspectRatio ?? "16:9",
                    videoResolution: item.data.videoResolution ?? "720P",
                    videoDuration: item.data.videoDuration ?? 5,
                    videoAudio: item.data.videoAudio ?? true,
                    videoCount: item.data.videoCount ?? 1,
                  },
                }
              : item,
          ),
          ...sourceNodes,
        ],
        edges: [
          ...activeCanvas.edges,
          ...sourceNodes.map((source) => connectNodes(source.id, node.id)),
        ],
      };
      commitCanvas(updated);
      setSelectedNodeId(node.id);
    },
    [
      activeCanvas,
      commitCanvas,
      modelOptions,
      prepareVideoReferenceFiles,
      setSelectedNodeId,
      t,
    ],
  );

  const handleVideoReferenceUpload = useCallback(
    async (
      node: AigcCanvasNode,
      mode: VideoReferenceMode,
      files?: FileList | null,
    ) => {
      if (!activeCanvas || !files?.length) return;
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const pickedFiles = Array.from(files).slice(
        0,
        referenceUploadLimit(mode),
      );
      const preparedFiles = await prepareVideoReferenceFiles(node, pickedFiles);
      if (!preparedFiles) return;
      const selectedVideoModel = modelForNode(
        modelOptions,
        node,
        "text_to_video",
      );
      const currentModelLabel =
        selectedVideoModel?.model_name ?? selectedVideoModel?.model_id;
      const sourceNodes: AigcCanvasNode[] = preparedFiles.map((source, index) => {
        const file = source.file;
        const assetKind = source.assetKind;
        return {
          id: `video-reference-${seed}-${index + 1}`,
          type: "reference_asset",
          position: {
            x: Math.max(80, node.position.x - 520),
            y: node.position.y + index * 230,
          },
          data: {
            title: referenceSourceLabel(t, mode, file, index),
            text: "",
            previewKind: "uploaded_source",
            assetShape: assetKind === "audio" ? "compact" : "wide",
            assetKind,
            assetName: source.assetName,
            assetPath: source.assetPath,
            assetMimeType: source.assetMimeType,
            assetPreviewUrl: source.assetPreviewUrl,
            savedToAssets: source.savedToAssets,
            uploadedAt: Date.now(),
          },
        };
      });
      const primary = sourceNodes[0];
      const targetPosition = {
        x: Math.max(
          node.position.x,
          (primary?.position.x ?? node.position.x) + 560,
        ),
        y: node.position.y,
      };
      const videoReferenceAssets = sourceNodes.map((source, index) => ({
        id: source.id,
        label: String(source.data.title ?? ""),
        name: String(source.data.assetName ?? ""),
        kind: String(source.data.assetKind ?? ""),
        previewUrl: String(source.data.assetPreviewUrl ?? ""),
        assetPath: source.data.assetPath,
        mimeType: source.data.assetMimeType,
        role: mode === "first_frame" && index === 1 ? "last_frame" : mode,
      }));
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
                    title: t("aigcStudio.videoNode.title", "视频节点"),
                    text: referenceModePrompt(t, mode),
                    videoMode: referenceModeVideoMode(mode),
                    activeVideoTab: mode,
                    showTryOptions: false,
                    referenceThumb: true,
                    referenceAssetName: preparedFiles
                      .map((source) => source.assetName)
                      .join(", "),
                    referencePreviewUrl: String(
                      primary?.data.assetPreviewUrl ?? "",
                    ),
                    referenceCount: pickedFiles.length,
                    videoReferenceAssets,
                    inputUpdated: true,
                    job_status: null,
                    outputs: [],
                    videoModel: currentModelLabel,
                    modelLabel: currentModelLabel,
                    providerId: selectedVideoModel?.provider_id,
                    modelId: selectedVideoModel?.model_id,
                    modelCapability: selectedVideoModel?.capability,
                    aspectRatio: item.data.aspectRatio ?? "16:9",
                    videoResolution: item.data.videoResolution ?? "720P",
                    videoDuration: item.data.videoDuration ?? 5,
                    videoAudio: item.data.videoAudio ?? true,
                    videoCount: item.data.videoCount ?? 1,
                  },
                }
              : item,
          ),
          ...sourceNodes,
        ],
        edges: [
          ...activeCanvas.edges,
          ...sourceNodes.map((source) => connectNodes(source.id, node.id)),
        ],
      };
      commitCanvas(updated);
      setSelectedNodeId(node.id);
    },
    [
      activeCanvas,
      commitCanvas,
      modelOptions,
      prepareVideoReferenceFiles,
      setSelectedNodeId,
      t,
    ],
  );

  const handleGeneratedVideoAction = useCallback(
    (node: AigcCanvasNode, action: VideoResultAction) => {
      if (!activeCanvas) return;
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const sourcePath = videoOutputPath(node);
      const sourceName = videoOutputName(node);
      const offsetY = downstreamResultActionCount(activeCanvas, node.id) * 220;
      const position = {
        x: node.position.x + 620,
        y: node.position.y + offsetY,
      };
      const sharedSourceData = {
        sourceVideoNodeId: node.id,
        sourceVideoName: sourceName,
        sourceVideoOutputPath: sourcePath,
        referenceAssetName: sourceName,
        referencePreviewUrl: sourcePath,
      };
      let targetNode: AigcCanvasNode;

      if (action === "analyze") {
        targetNode = {
          id: `video-analysis-${seed}`,
          type: "prompt",
          position,
          data: {
            title: t("aigcStudio.videoNode.result.analysisTitle", "视频解析"),
            text: t(
              "aigcStudio.videoNode.result.analysisPrompt",
              "解析视频内容、镜头、主体、动作和可复用提示词。",
            ),
            composerText: "",
            textMode: "video_analysis",
            showTryOptions: false,
            inputUpdated: true,
            referenceThumb: true,
            ...sharedSourceData,
          },
        };
      } else if (action === "extract_audio") {
        targetNode = {
          id: `video-audio-${seed}`,
          type: "reference_asset",
          position,
          data: {
            title: t("aigcStudio.videoNode.result.audioTitle", "分离音频"),
            text: t(
              "aigcStudio.videoNode.result.audioDescription",
              "从视频中分离出的音频轨道。",
            ),
            previewKind: "audio_from_video",
            assetKind: "audio",
            assetName: `${sourceName} · audio`,
            assetPreviewUrl: sourcePath,
            participatesInGeneration: true,
            ...sharedSourceData,
          },
        };
      } else {
        const config = videoDerivativeConfig(t, action);
        targetNode = {
          id: `${config.idPrefix}-${seed}`,
          type: "video_generate",
          position,
          data: {
            title: config.title,
            text: config.text,
            composerText: "",
            videoMode: config.videoMode,
            activeVideoTab: "all_reference",
            videoState: "editing",
            videoProgress: null,
            job_status: null,
            outputs: [],
            showTryOptions: false,
            inputUpdated: true,
            referenceThumb: true,
            referenceVideoNodeId: node.id,
            referenceCount: 1,
            ...sharedSourceData,
            aspectRatio: node.data.aspectRatio ?? "16:9",
            videoResolution:
              config.videoResolution ?? node.data.videoResolution ?? "720P",
            videoDuration: node.data.videoDuration ?? 5,
            videoAudio: node.data.videoAudio ?? true,
            videoCount: 1,
            ...(config.extraData ?? {}),
          },
        };
      }

      commitCanvas({
        ...activeCanvas,
        nodes: [...activeCanvas.nodes, targetNode],
        edges: [...activeCanvas.edges, connectNodes(node.id, targetNode.id)],
      });
      setSelectedNodeId(targetNode.id);
    },
    [activeCanvas, commitCanvas, setSelectedNodeId, t],
  );

  const handleVideoCancelGeneration = useCallback(
    (node: AigcCanvasNode) => {
      updateNodeData(node.id, {
        job_status: "cancelled",
        videoState: "failed",
        videoProgress: null,
        job_error: t("aigcStudio.videoNode.cancelledHint", "已取消生成"),
      });
    },
    [t, updateNodeData],
  );

  const handleVideoRetryGeneration = useCallback(
    (node: AigcCanvasNode) => {
      updateNodeData(node.id, {
        job_status: "running",
        videoState: "generating",
        videoProgress: 1,
        error: null,
        job_error: null,
        outputs: [],
      });
    },
    [updateNodeData],
  );

  const handleVideoComposerSubmit = useCallback(
    (node: AigcCanvasNode) => {
      const prompt = String(
        node.data.composerText ?? node.data.text ?? "",
      ).trim();
      const selectedVideoModel = modelForNode(
        modelOptions,
        node,
        "text_to_video",
      );
      const currentModelLabel =
        selectedVideoModel?.model_name ?? selectedVideoModel?.model_id;

      const nextData = {
        text: prompt || node.data.text || "",
        lastRunPrompt: prompt,
        showTryOptions: false,
        videoModel: currentModelLabel,
        modelLabel: currentModelLabel,
        providerId: selectedVideoModel?.provider_id,
        modelId: selectedVideoModel?.model_id,
        modelCapability: selectedVideoModel?.capability,
        aspectRatio: node.data.aspectRatio ?? "16:9",
        videoResolution: node.data.videoResolution ?? "720P",
        videoDuration: node.data.videoDuration ?? 5,
        videoAudio: node.data.videoAudio ?? true,
        videoCount: node.data.videoCount ?? 1,
      };
      const nodeSnapshot = {
        ...node,
        data: {
          ...node.data,
          ...nextData,
        },
      };
      updateNodeData(node.id, nextData);
      void onRunNode?.(nodeSnapshot);
      return nodeSnapshot;
    },
    [modelOptions, onRunNode, updateNodeData],
  );

  return {
    handleVideoUpload,
    handleVideoTryUpload,
    handleVideoReferenceUpload,
    handleGeneratedVideoAction,
    handleVideoCancelGeneration,
    handleVideoRetryGeneration,
    handleVideoComposerSubmit,
  };
}
