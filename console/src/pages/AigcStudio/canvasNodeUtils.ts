import type { useTranslation } from "react-i18next";

import type { AigcAsset, AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  isStoryboardImageNode,
  scriptMode,
  storyboardImageMode,
} from "./components/ScriptNode/scriptNodeState";
import { nodeDefinition } from "./domain/componentRegistry";

const DEFAULT_IMAGE_DISPLAY_RATIO = "16:9";
const IMAGE_NODE_LONG_EDGE = 560;
const IMAGE_NODE_MIN_EDGE = 220;
const DEFAULT_VIDEO_DISPLAY_RATIO = "16:9";
const VIDEO_NODE_LONG_EDGE = 660;
const VIDEO_NODE_MIN_EDGE = 280;
const UPLOADED_IMAGE_LONG_EDGE = 360;
const LONG_IMAGE_EXPORT_NODE_HEIGHT = 160;

export type Translate = ReturnType<typeof useTranslation>["t"];
export type CanvasFileKind = "image" | "video" | "audio";

export type CanvasAssetRecord = {
  id: string;
  title: string;
  kind: string;
  nodeType: string;
  sourceNodeId: string;
  text: string;
  previewKind?: string;
  assetPreviewUrl?: string;
  createdAt: number;
};

export const NODE_TYPE_FALLBACKS: Record<string, string> = {
  prompt: "提示词/文本",
  reference_asset: "参考素材",
  reference_note: "参考节点",
  image_generate: "图片生成/编辑",
  video_generate: "视频生成",
  long_image_export: "公众号长图",
  video_compose: "视频合成",
  director_stage: "导演台",
  audio_generate: "音频生成",
  script_generate: "脚本生成",
  output: "输出/导出",
};

export const CAPABILITY_FALLBACKS: Record<string, string> = {
  text_to_image: "文生图",
  image_edit: "图片编辑",
  image_to_image: "图生图",
  mask_edit: "局部重绘",
  reference_image: "参考图",
  text_to_video: "文生视频",
  image_to_video: "图生视频",
  reference_video: "参考视频",
  text_to_audio: "文生音频",
  storyboard: "分镜",
  long_image_export: "长图导出",
};

export const JOB_STATUS_FALLBACKS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function translatedCapability(t: Translate, capability: string) {
  return t(
    `aigcStudio.capability.${capability}`,
    CAPABILITY_FALLBACKS[capability] ?? capability,
  );
}

export function translatedNodeType(t: Translate, type: string) {
  return t(`aigcStudio.nodeType.${type}`, NODE_TYPE_FALLBACKS[type] ?? type);
}

export function nodeTitle(t: Translate, type: string) {
  const definition = nodeDefinition(type);
  return definition
    ? t(definition.titleKey, definition.titleFallback)
    : translatedNodeType(t, type);
}

export function nodeWidth(type: string) {
  if (type === "prompt") return 400;
  if (type === "reference_note") return 400;
  if (type === "image_generate") return 560;
  if (type === "video_generate") return 660;
  if (type === "long_image_export") return 420;
  if (type === "script_generate") return 350;
  return type === "video_compose" ? 320 : 260;
}

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const recordValue = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const parseAspectRatio = (value: unknown) => {
  if (typeof value !== "string") return null;
  const clean = value.trim();
  if (!clean || clean === "自适应") return null;
  const match = clean.match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
  if (width <= 0 || height <= 0) return null;
  return { width, height };
};

const generatedImageRatioFromOutput = (node: AigcCanvasNode) => {
  const primaryOutput = nodePrimaryOutput(node) as
    | (AigcAsset & Record<string, unknown>)
    | undefined;
  if (!primaryOutput) return null;

  const width = numberValue(primaryOutput.width);
  const height = numberValue(primaryOutput.height);
  if (width && height) return { width, height };

  const meta = recordValue(primaryOutput.meta);
  const parameters = recordValue(meta?.parameters);
  return (
    parseAspectRatio(parameters?.aspectRatio) ??
    parseAspectRatio(parameters?.aspect_ratio) ??
    parseAspectRatio(meta?.aspectRatio) ??
    parseAspectRatio(meta?.aspect_ratio)
  );
};

const isGeneratedImageNode = (node: AigcCanvasNode) =>
  node.type === "image_generate" &&
  (node.data.imageState === "generated" ||
    (node.data.job_status === "succeeded" && nodeOutputs(node).length > 0));

const imageNodeDisplayRatio = (node: AigcCanvasNode) => {
  if (isGeneratedImageNode(node)) {
    return (
      generatedImageRatioFromOutput(node) ??
      parseAspectRatio(node.data.generatedAspectRatio) ??
      parseAspectRatio(DEFAULT_IMAGE_DISPLAY_RATIO)
    );
  }
  return (
    parseAspectRatio(node.data.aspectRatio) ??
    parseAspectRatio(DEFAULT_IMAGE_DISPLAY_RATIO)
  );
};

const imageNodeDisplaySize = (node: AigcCanvasNode) => {
  const ratio = imageNodeDisplayRatio(node);
  if (!ratio) {
    return { width: IMAGE_NODE_LONG_EDGE, height: 320 };
  }

  if (ratio.width >= ratio.height) {
    return {
      width: IMAGE_NODE_LONG_EDGE,
      height: Math.max(
        IMAGE_NODE_MIN_EDGE,
        Math.round((IMAGE_NODE_LONG_EDGE * ratio.height) / ratio.width),
      ),
    };
  }

  return {
    width: Math.max(
      IMAGE_NODE_MIN_EDGE,
      Math.round((IMAGE_NODE_LONG_EDGE * ratio.width) / ratio.height),
    ),
    height: IMAGE_NODE_LONG_EDGE,
  };
};

const generatedVideoRatioFromOutput = (node: AigcCanvasNode) => {
  const output = nodeOutputs(node).find((asset) => asset.kind === "video") as
    | (AigcAsset & Record<string, unknown>)
    | undefined;
  if (!output) return null;

  const width = numberValue(output.width);
  const height = numberValue(output.height);
  if (width && height) return { width, height };

  const meta = recordValue(output.meta);
  const parameters = recordValue(meta?.parameters);
  return (
    parseAspectRatio(parameters?.aspectRatio) ??
    parseAspectRatio(parameters?.aspect_ratio) ??
    parseAspectRatio(meta?.aspectRatio) ??
    parseAspectRatio(meta?.aspect_ratio)
  );
};

const videoFrameRatio = (value: unknown) =>
  textValue(value).replace(/\s+/g, "") === "9:16"
    ? parseAspectRatio("9:16")
    : parseAspectRatio(DEFAULT_VIDEO_DISPLAY_RATIO);

const isGeneratedVideoNode = (node: AigcCanvasNode) =>
  node.type === "video_generate" &&
  (node.data.videoState === "generated" ||
    (node.data.job_status === "succeeded" &&
      nodeOutputs(node).some((asset) => asset.kind === "video")));

const videoNodeDisplayRatio = (node: AigcCanvasNode) => {
  if (isGeneratedVideoNode(node)) {
    const selectedRatio =
      textValue(node.data.generatedAspectRatio) ||
      textValue(node.data.aspectRatio);
    if (selectedRatio) return videoFrameRatio(selectedRatio);
    const outputRatio = generatedVideoRatioFromOutput(node);
    return outputRatio && outputRatio.width < outputRatio.height
      ? videoFrameRatio("9:16")
      : videoFrameRatio(DEFAULT_VIDEO_DISPLAY_RATIO);
  }
  return videoFrameRatio(node.data.aspectRatio);
};

const videoNodeDisplaySize = (node: AigcCanvasNode) => {
  const ratio = videoNodeDisplayRatio(node);
  if (!ratio) return { width: VIDEO_NODE_LONG_EDGE, height: 370 };

  if (ratio.width >= ratio.height) {
    return {
      width: VIDEO_NODE_LONG_EDGE,
      height: Math.max(
        VIDEO_NODE_MIN_EDGE,
        Math.round((VIDEO_NODE_LONG_EDGE * ratio.height) / ratio.width),
      ),
    };
  }

  return {
    width: Math.max(
      VIDEO_NODE_MIN_EDGE,
      Math.round((VIDEO_NODE_LONG_EDGE * ratio.width) / ratio.height),
    ),
    height: VIDEO_NODE_LONG_EDGE,
  };
};

const annotationNodeDisplaySize = (node: AigcCanvasNode) => {
  const ratio =
    parseAspectRatio(node.data.annotationAspectRatio) ??
    (() => {
      const width = numberValue(node.data.sourceImageWidth);
      const height = numberValue(node.data.sourceImageHeight);
      return width && height ? { width, height } : null;
    })() ??
    parseAspectRatio(DEFAULT_IMAGE_DISPLAY_RATIO);
  if (!ratio) {
    return { width: IMAGE_NODE_LONG_EDGE, height: 320 };
  }

  if (ratio.width >= ratio.height) {
    return {
      width: IMAGE_NODE_LONG_EDGE,
      height: Math.max(
        IMAGE_NODE_MIN_EDGE,
        Math.round((IMAGE_NODE_LONG_EDGE * ratio.height) / ratio.width),
      ),
    };
  }

  return {
    width: Math.max(
      IMAGE_NODE_MIN_EDGE,
      Math.round((IMAGE_NODE_LONG_EDGE * ratio.width) / ratio.height),
    ),
    height: IMAGE_NODE_LONG_EDGE,
  };
};

const uploadedAssetImageRatio = (node: AigcCanvasNode) => {
  const width =
    numberValue(node.data.assetWidth) ??
    numberValue(node.data.sourceImageWidth);
  const height =
    numberValue(node.data.assetHeight) ??
    numberValue(node.data.sourceImageHeight);
  if (width && height) return { width, height };
  return parseAspectRatio(node.data.assetAspectRatio);
};

const uploadedAssetDisplaySize = (node: AigcCanvasNode) => {
  const ratio = uploadedAssetImageRatio(node);
  if (!ratio) return { width: 280, height: 420 };
  if (ratio.width >= ratio.height) {
    return {
      width: UPLOADED_IMAGE_LONG_EDGE,
      height: Math.max(
        1,
        Math.round((UPLOADED_IMAGE_LONG_EDGE * ratio.height) / ratio.width),
      ),
    };
  }
  return {
    width: Math.max(
      1,
      Math.round((UPLOADED_IMAGE_LONG_EDGE * ratio.width) / ratio.height),
    ),
    height: UPLOADED_IMAGE_LONG_EDGE,
  };
};

export function nodeVisualWidth(node: AigcCanvasNode) {
  if (isStoryboardImageNode(node)) {
    if (storyboardImageMode(node) !== "grid") return 330;
    return 880;
  }
  if (node.type === "script_generate") {
    if (node.data.scriptFullscreen === true) return 1600;
    const mode = scriptMode(node);
    if (
      mode === "script_ready" ||
      mode === "storyboard_select" ||
      mode === "storyboard_image_generating" ||
      mode === "storyboard_grid" ||
      mode === "generating_script"
    ) {
      return 350;
    }
    return 350;
  }
  if (isImageAnnotationNode(node)) {
    return annotationNodeDisplaySize(node).width;
  }
  if (
    node.data.previewKind === "uploaded_source" ||
    node.data.previewKind === "style_template"
  ) {
    return uploadedAssetDisplaySize(node).width;
  }
  if (node.data.previewKind === "script_asset_group") return 430;
  if (node.data.previewKind === "image_capture_group") {
    return Number(node.data.captureCount ?? 0) > 4 ? 760 : 620;
  }
  if (node.data.previewKind === "storyboard_video_batch") return 1600;
  if (node.type === "image_generate" && node.data.imageMode === "upscale") {
    return 380;
  }
  if (node.type === "image_generate") return imageNodeDisplaySize(node).width;
  if (node.type === "video_generate") return videoNodeDisplaySize(node).width;
  if (node.data.assetShape === "wide") return 450;
  return nodeWidth(node.type);
}

export function nodeVisualHeight(node: AigcCanvasNode) {
  if (isStoryboardImageNode(node)) {
    return storyboardImageMode(node) === "grid" ? 760 : 900;
  }
  if (node.type === "script_generate") {
    if (node.data.scriptFullscreen === true) return 760;
    const mode = scriptMode(node);
    if (
      mode === "script_ready" ||
      mode === "storyboard_select" ||
      mode === "storyboard_image_generating" ||
      mode === "storyboard_grid" ||
      mode === "generating_script"
    ) {
      return 350;
    }
    return 350;
  }
  if (isImageAnnotationNode(node)) {
    return annotationNodeDisplaySize(node).height;
  }
  if (node.data.previewKind === "storyboard_video_batch") return 520;
  if (node.data.previewKind === "image_capture_group") {
    return Number(node.data.captureCount ?? 0) > 4 ? 500 : 320;
  }
  if (
    node.data.previewKind === "uploaded_source" ||
    node.data.previewKind === "style_template"
  ) {
    return uploadedAssetDisplaySize(node).height;
  }
  if (node.data.previewKind === "script_asset_group") return 640;
  if (node.type === "video_generate") return videoNodeDisplaySize(node).height;
  if (node.type === "long_image_export") return LONG_IMAGE_EXPORT_NODE_HEIGHT;
  if (node.type === "image_generate") {
    if (node.data.imageMode === "upscale") return 340;
    return imageNodeDisplaySize(node).height;
  }
  if (node.type === "prompt" || node.type === "reference_note") return 180;
  return 150;
}

export function nodeOutputs(node: AigcCanvasNode): AigcAsset[] {
  return Array.isArray(node.data.outputs)
    ? (node.data.outputs as AigcAsset[])
    : [];
}

const primaryOutputIndex = (value: unknown) => {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) {
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    return Number(value);
  }
  return null;
};

export function nodePrimaryOutput(node: AigcCanvasNode): AigcAsset | undefined {
  const outputs = nodeOutputs(node);
  if (outputs.length === 0) return undefined;

  const primaryId = textValue(node.data.primaryOutputId);
  if (primaryId) {
    const matched = outputs.find(
      (output) => textValue(output.id) === primaryId,
    );
    if (matched) return matched;
  }

  const index = primaryOutputIndex(node.data.primaryOutputIndex);
  if (index !== null && outputs[index]) return outputs[index];

  return outputs[0];
}

export function nodePrimaryOutputPreviewSource(node: AigcCanvasNode) {
  const primaryOutput = nodePrimaryOutput(node);
  return primaryOutput ? assetPreviewSource(primaryOutput) ?? "" : "";
}

export function nodePrimaryOutputName(node: AigcCanvasNode) {
  const firstOutput = nodePrimaryOutput(node);
  const name =
    typeof firstOutput?.name === "string" ? firstOutput.name.trim() : "";
  if (name) return name;
  const path =
    typeof firstOutput?.path === "string" ? firstOutput.path.trim() : "";
  if (path) return path.split("/").pop() || path;
  return "";
}

export function shouldRenderNodeOutputList(node: AigcCanvasNode) {
  return (
    node.type !== "image_generate" &&
    node.type !== "video_generate" &&
    node.type !== "long_image_export" &&
    node.type !== "prompt" &&
    node.type !== "script_generate" &&
    nodeOutputs(node).length > 0
  );
}

const PREVIEWABLE_ASSET_SOURCE_RE = /^(https?:|data:|blob:|\/)/i;

export function assetPreviewSource(asset: { path?: unknown; url?: unknown }) {
  const url = typeof asset.url === "string" ? asset.url.trim() : "";
  if (url) return url;

  const path = typeof asset.path === "string" ? asset.path.trim() : "";
  return PREVIEWABLE_ASSET_SOURCE_RE.test(path) ? path : undefined;
}

export function pickNodeData(
  data: Record<string, unknown>,
  keys: string[],
): Record<string, unknown> {
  return keys.reduce<Record<string, unknown>>((result, key) => {
    const value = data[key];
    if (value !== undefined && value !== null && value !== "") {
      result[key] = value;
    }
    return result;
  }, {});
}

const firstNonEmptyString = (...values: unknown[]) =>
  values.map((value) => String(value ?? "").trim()).find(Boolean);

export function nodeReferenceName(node: AigcCanvasNode) {
  if (node.type === "image_generate") {
    return firstNonEmptyString(
      nodePrimaryOutputName(node),
      node.data.assetName,
      node.data.referenceAssetName,
      node.data.title,
    );
  }
  return firstNonEmptyString(
    node.data.assetName,
    node.data.referenceAssetName,
    nodePrimaryOutputName(node),
    node.data.title,
  );
}

export function nodeReferencePreviewSource(node: AigcCanvasNode) {
  if (node.type === "image_generate") {
    return firstNonEmptyString(
      nodePrimaryOutputPreviewSource(node),
      node.data.assetPreviewUrl,
      node.data.referencePreviewUrl,
    );
  }
  return firstNonEmptyString(
    node.data.assetPreviewUrl,
    node.data.referencePreviewUrl,
    nodePrimaryOutputPreviewSource(node),
  );
}

const IMAGE_ANNOTATION_MARKERS = new Set([
  "annotation",
  "image_annotation",
  "image_region",
  "region_annotation",
  "region_edit",
]);

function annotationSourcePreviewUrlFromNode(node: AigcCanvasNode) {
  return firstNonEmptyString(
    node.data.annotationSourcePreviewUrl,
    node.data.sourcePreviewUrl,
    node.data.originalPreviewUrl,
    node.data.referencePreviewUrl,
    node.data.assetPreviewUrl,
    nodePrimaryOutputPreviewSource(node),
  );
}

function annotationPreviewUrlFromNode(node: AigcCanvasNode) {
  return firstNonEmptyString(
    node.data.annotationPreviewUrl,
    node.data.annotatedPreviewUrl,
    node.data.maskPreviewUrl,
    node.data.markPreviewUrl,
    node.data.assetPreviewUrl,
    nodePrimaryOutputPreviewSource(node),
  );
}

function annotationInstructionFromNode(node: AigcCanvasNode) {
  return firstNonEmptyString(
    node.data.annotationInstruction,
    node.data.instruction,
    node.data.annotationText,
    node.data.text,
    node.data.composerText,
    node.data.annotationLabel,
    node.data.markPreset,
  );
}

export function isImageAnnotationNode(node?: AigcCanvasNode | null) {
  if (!node) return false;
  if (node.data.isAnnotation === true) return true;
  const markerValues = [
    node.data.assetRole,
    node.data.assetKind,
    node.data.previewKind,
    node.data.imageMode,
    node.data.annotationKind,
    node.data.role,
  ];
  if (
    markerValues.some((value) =>
      IMAGE_ANNOTATION_MARKERS.has(String(value ?? "").trim()),
    )
  ) {
    return true;
  }

  const title = String(node.data.title ?? "").trim();
  if (!["标注", "图像标注", "Annotation"].includes(title)) return false;
  return Boolean(
    firstNonEmptyString(
      node.data.assetPreviewUrl,
      node.data.referencePreviewUrl,
      node.data.annotationPreviewUrl,
      node.data.annotationSourcePreviewUrl,
      nodePrimaryOutputPreviewSource(node),
    ),
  );
}

export function annotationInputFromNode(node: AigcCanvasNode) {
  const sourcePreviewUrl = annotationSourcePreviewUrlFromNode(node);
  const annotationPreviewUrl = annotationPreviewUrlFromNode(node);
  return {
    node_id: node.id,
    type: node.type,
    title: node.data.title,
    role: "image_annotation",
    asset_name: firstNonEmptyString(
      node.data.assetName,
      node.data.referenceAssetName,
      nodePrimaryOutputName(node),
    ),
    preview_url: sourcePreviewUrl || annotationPreviewUrl,
    source_preview_url: sourcePreviewUrl,
    annotated_preview_url: annotationPreviewUrl,
    instruction: annotationInstructionFromNode(node),
    target: firstNonEmptyString(
      node.data.annotationTarget,
      node.data.annotationLabel,
      node.data.markPreset,
    ),
  };
}

export function referenceInputFromNode(node: AigcCanvasNode) {
  if (isImageAnnotationNode(node)) {
    return annotationInputFromNode(node);
  }
  return {
    node_id: node.id,
    type: node.type,
    title: node.data.title,
    asset_name:
      node.type === "prompt"
        ? firstNonEmptyString(
            node.data.assetName,
            node.data.referenceAssetName,
            nodePrimaryOutputName(node),
          )
        : nodeReferenceName(node),
    preview_url: nodeReferencePreviewSource(node),
  };
}

export function isStyleTemplateNode(node?: AigcCanvasNode | null) {
  if (!node) return false;
  if (node.type !== "reference_asset") return false;
  return (
    String(node.data.assetRole ?? "") === "style_template" ||
    String(node.data.assetKind ?? "") === "style_template" ||
    String(node.data.assetKind ?? "") === "style" ||
    String(node.data.previewKind ?? "") === "style_template" ||
    Boolean(node.data.styleTemplateUuid || node.data.effectTemplateUuid)
  );
}

export function canvasAssetFromNode(
  t: Translate,
  node: AigcCanvasNode,
  kind: string,
  id = `asset-${Date.now().toString(36)}-${node.id}`,
): CanvasAssetRecord {
  return {
    id,
    title: String(node.data.title ?? translatedNodeType(t, node.type)),
    kind,
    nodeType: node.type,
    sourceNodeId: node.id,
    text: String(node.data.text ?? node.data.composerText ?? ""),
    previewKind:
      typeof node.data.previewKind === "string"
        ? node.data.previewKind
        : undefined,
    assetPreviewUrl:
      typeof node.data.assetPreviewUrl === "string"
        ? node.data.assetPreviewUrl
        : typeof node.data.referencePreviewUrl === "string"
        ? node.data.referencePreviewUrl
        : nodePrimaryOutputPreviewSource(node) || undefined,
    createdAt:
      typeof node.data.savedAt === "number" ? node.data.savedAt : Date.now(),
  };
}

export function assetKindFromFile(file: File): CanvasFileKind {
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  return "image";
}

export function assetPreviewKind(kind: CanvasFileKind) {
  if (kind === "video") return "uploaded_video";
  if (kind === "audio") return "audio_source";
  return "uploaded_source";
}
