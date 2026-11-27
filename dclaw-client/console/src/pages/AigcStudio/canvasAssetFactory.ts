import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasNode,
  CanvasPayload,
} from "../../api/modules/aigcStudio";
import {
  assetKindFromFile,
  assetPreviewKind,
  type Translate,
} from "./canvasNodeUtils";

export type CanvasPoint = { x: number; y: number };

const LEGACY_CANVAS_NAMES = new Set([
  "Untitled AIGC canvas",
  "Untitled canvas",
]);

const LEGACY_NODE_TEXT_KEYS: Record<string, string> = {
  "Campaign prompt": "aigcStudio.defaultNodes.prompt.title",
  "A cinematic product film concept with clear brand mood.":
    "aigcStudio.defaultNodes.prompt.text",
  "Hero image": "aigcStudio.defaultNodes.image.title",
  "Generate image variants from the selected prompt.":
    "aigcStudio.defaultNodes.image.text",
  "Motion clip": "aigcStudio.defaultNodes.video.title",
  "Use generated keyframes and references for video.":
    "aigcStudio.defaultNodes.video.text",
  "Reference board": "aigcStudio.defaultNodes.reference.title",
  "Collect character, object, style and brand assets.":
    "aigcStudio.defaultNodes.reference.text",
};

const CHINESE_FALLBACKS: Record<string, string> = {
  "aigcStudio.defaultName": "未命名 AIGC 画布",
  "aigcStudio.defaultNodes.prompt.title": "营销提示词",
  "aigcStudio.defaultNodes.prompt.text": "带有清晰品牌氛围的电影感产品片创意。",
  "aigcStudio.defaultNodes.image.title": "主视觉图片",
  "aigcStudio.defaultNodes.image.text": "基于选中的提示词生成图片变体。",
  "aigcStudio.defaultNodes.video.title": "动态片段",
  "aigcStudio.defaultNodes.video.text": "使用生成的关键帧和参考素材生成视频。",
  "aigcStudio.defaultNodes.reference.title": "参考素材板",
  "aigcStudio.defaultNodes.reference.text": "收集角色、物体、风格和品牌资产。",
};

const TRANSIENT_NODE_DATA_KEYS = new Set(["activeTool"]);

function persistableNode(node: AigcCanvasNode): AigcCanvasNode {
  const data = Object.fromEntries(
    Object.entries(node.data).filter(
      ([key]) => !TRANSIENT_NODE_DATA_KEYS.has(key),
    ),
  );
  return {
    ...node,
    data,
  };
}

export function canvasPayload(canvas: AigcCanvas): CanvasPayload {
  return {
    name: canvas.name,
    nodes: canvas.nodes.map(persistableNode),
    edges: canvas.edges,
    viewport: canvas.viewport,
    thumbnail: canvas.thumbnail,
    meta: canvas.meta,
  };
}

export function canvasSignature(canvas: AigcCanvas) {
  return JSON.stringify({
    id: canvas.id,
    ...canvasPayload(canvas),
  });
}

function localizeLegacyText(t: Translate, value: unknown) {
  if (typeof value !== "string") return value;
  const key = LEGACY_NODE_TEXT_KEYS[value];
  return key ? t(key, CHINESE_FALLBACKS[key] ?? value) : value;
}

export function localizeLegacyCanvas(
  t: Translate,
  canvas: AigcCanvas,
): AigcCanvas {
  const name = LEGACY_CANVAS_NAMES.has(canvas.name)
    ? t("aigcStudio.defaultName", "未命名 AIGC 画布")
    : canvas.name;
  return {
    ...canvas,
    name,
    nodes: canvas.nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        title: localizeLegacyText(t, node.data.title),
        text: localizeLegacyText(t, node.data.text),
      },
    })),
  };
}

export function createAssetPreviewUrl(file: File) {
  try {
    if (typeof URL !== "undefined" && URL.createObjectURL) {
      return URL.createObjectURL(file);
    }
  } catch {
    return "";
  }
  return "";
}

export function createAssetNodeFromUpload(
  t: Translate,
  asset: AigcAsset,
  file: File,
  index: number,
  position: CanvasPoint,
  nodeCount: number,
): AigcCanvasNode {
  const kind = assetKindFromFile(file);
  const previewUrl = asset.url || createAssetPreviewUrl(file);
  return {
    id: `asset-node-${Date.now().toString(36)}-${nodeCount + index + 1}`,
    type: "reference_asset",
    position: {
      x: position.x + index * 44,
      y: position.y + index * 28,
    },
    data: {
      title:
        kind === "video"
          ? t("aigcStudio.assetNode.video", "视频素材")
          : kind === "audio"
          ? t("aigcStudio.assetNode.audio", "音频素材")
          : t("aigcStudio.assetNode.image", "图片节点"),
      text: "",
      previewKind: assetPreviewKind(kind),
      assetKind: kind,
      assetName: asset.name || file.name,
      assetPath: asset.path,
      assetMimeType: asset.mime_type || file.type,
      assetPreviewUrl: previewUrl,
      assetShape: kind === "video" ? "wide" : undefined,
      savedToAssets: true,
      uploadedAt: Date.now(),
    },
  };
}
