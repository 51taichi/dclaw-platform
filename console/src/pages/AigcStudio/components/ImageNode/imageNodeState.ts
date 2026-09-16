import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import type { ImageSlashCommand } from "./types";

export const DEFAULT_IMAGE_ASPECT_RATIO = "16:9";
export const PANORAMA_IMAGE_ASPECT_RATIO = "2:1";
export const DEFAULT_IMAGE_RESOLUTION = "2K";
export const DEFAULT_IMAGE_QUALITY = "标准画质";
export const DEFAULT_IMAGE_CAMERA_PRESET = {
  cameraProfile: "电影镜头",
  cameraBody: "Panavision DXL2",
  lens: "Arri Signature Prime",
  focal: "35 mm",
  aperture: "f/4",
};

export const IMAGE_QUALITY_OPTIONS = ["低画质", "标准画质", "高画质"];
export const IMAGE_RESOLUTION_OPTIONS = ["1K", "2K", "4K"];
export const IMAGE_STYLE_OPTIONS = ["电影感", "写实", "插画", "产品棚拍"];
export const IMAGE_MARK_OPTIONS = [
  "主体区域",
  "背景区域",
  "细节区域",
  "边缘区域",
];
export const IMAGE_FOCUS_OPTIONS = [
  "主体清晰",
  "景深虚化",
  "全局清晰",
  "氛围优先",
];
export const IMAGE_ASPECT_RATIO_OPTIONS = [
  "自适应",
  "1:1",
  "1:2",
  "2:1",
  "9:16",
  "16:9",
  "3:4",
  "4:3",
  "3:2",
  "2:3",
  "4:5",
  "5:4",
  "21:9",
  "9:21",
];

export type ImageNodeState =
  | "empty"
  | "editing"
  | "generating"
  | "generated"
  | "failed";

const IMAGE_NODE_STATES = new Set<ImageNodeState>([
  "empty",
  "editing",
  "generating",
  "generated",
  "failed",
]);

const stringValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

export const imageModelDisplayName = (value: unknown) => {
  const label = stringValue(value);
  return label.replace(/\s+-\s+MXAPI$/i, "");
};

export const imageModelKey = (model: AigcCapabilityInfo) =>
  `${model.provider_id}:${model.model_id}`;

export const IMAGE_GENERATION_CAPABILITIES = new Set([
  "text_to_image",
  "image_to_image",
  "image_edit",
  "mask_edit",
]);

const IMAGE_CAPABILITY_PRIORITY = [
  "text_to_image",
  "image_to_image",
  "image_edit",
  "mask_edit",
];

const imageCapabilityRank = (capability: string) => {
  const index = IMAGE_CAPABILITY_PRIORITY.indexOf(capability);
  return index === -1 ? IMAGE_CAPABILITY_PRIORITY.length : index;
};

export const isImageCapabilityModel = (
  model?: AigcCapabilityInfo | null,
) => Boolean(model && IMAGE_GENERATION_CAPABILITIES.has(model.capability));

export const imageModelOptionsFrom = (modelOptions: AigcCapabilityInfo[]) => {
  const uniqueModels = new Map<string, AigcCapabilityInfo>();
  modelOptions.filter(isImageCapabilityModel).forEach((model) => {
    const key = imageModelKey(model);
    const existing = uniqueModels.get(key);
    if (
      !existing ||
      imageCapabilityRank(model.capability) <
        imageCapabilityRank(existing.capability)
    ) {
      uniqueModels.set(key, model);
    }
  });
  return Array.from(uniqueModels.values());
};

export const imageModelForNode = (
  node: AigcCanvasNode,
  currentModel?: AigcCapabilityInfo | null,
  modelOptions: AigcCapabilityInfo[] = [],
) => {
  if (isImageCapabilityModel(currentModel)) return currentModel;
  const nodeProviderId = stringValue(node.data.providerId);
  const nodeModelId = stringValue(node.data.modelId);
  const nodeModelCapability = stringValue(node.data.modelCapability);
  const nodeModelKey =
    nodeProviderId && nodeModelId ? `${nodeProviderId}:${nodeModelId}` : "";
  const exactNodeModel = modelOptions.find(
    (model) =>
      isImageCapabilityModel(model) &&
      imageModelKey(model) === nodeModelKey &&
      (!nodeModelCapability || model.capability === nodeModelCapability),
  );
  if (exactNodeModel) return exactNodeModel;
  const imageModelOptions = imageModelOptionsFrom(modelOptions);
  const matchedNodeModel = imageModelOptions.find(
    (model) => imageModelKey(model) === nodeModelKey,
  );
  if (matchedNodeModel) return matchedNodeModel;
  if (
    nodeProviderId &&
    nodeModelId &&
    (!imageModelOptions.length ||
      IMAGE_GENERATION_CAPABILITIES.has(nodeModelCapability))
  ) {
    return {
      provider_id: nodeProviderId,
      provider_name: stringValue(node.data.providerName) || nodeProviderId,
      model_id: nodeModelId,
      model_name: imageModelDisplayName(node.data.modelLabel) || nodeModelId,
      capability: nodeModelCapability || "text_to_image",
      source: "model_registry" as const,
    };
  }
  return imageModelOptions[0] ?? null;
};

const hasOutputs = (node: AigcCanvasNode) =>
  Array.isArray(node.data.outputs) && node.data.outputs.length > 0;

const hasEditingInput = (node: AigcCanvasNode) =>
  Boolean(
    stringValue(node.data.text) ||
      stringValue(node.data.composerText) ||
      stringValue(node.data.lastRunPrompt) ||
      stringValue(node.data.referenceAssetName) ||
      stringValue(node.data.referencePreviewUrl) ||
      stringValue(node.data.assetName) ||
      stringValue(node.data.assetPreviewUrl) ||
      node.data.referenceThumb === true ||
      node.data.inputUpdated === true ||
      (stringValue(node.data.imageMode) &&
        stringValue(node.data.imageMode) !== "blank") ||
      (stringValue(node.data.previewKind) &&
        stringValue(node.data.previewKind) !== "empty"),
  );

export const imageNodeStateFromNode = (
  node: AigcCanvasNode,
): ImageNodeState => {
  const explicitState = stringValue(node.data.imageState);
  const jobStatus = stringValue(node.data.job_status);

  if (explicitState === "failed" || jobStatus === "failed") return "failed";
  if (jobStatus === "cancelled") return "failed";
  if (
    explicitState === "generating" ||
    jobStatus === "queued" ||
    jobStatus === "running"
  ) {
    return "generating";
  }
  if (IMAGE_NODE_STATES.has(explicitState as ImageNodeState)) {
    return explicitState as ImageNodeState;
  }
  if (hasOutputs(node)) return "generated";
  if (hasEditingInput(node)) return "editing";
  return "empty";
};

export const isPanoramaImageNode = (node: AigcCanvasNode) =>
  node.data.panoramaMode === true ||
  stringValue(node.data.imageMode) === "panorama";

export const imageComposerSizeSummary = (node: AigcCanvasNode) => {
  const aspectRatio = isPanoramaImageNode(node)
    ? PANORAMA_IMAGE_ASPECT_RATIO
    : String(node.data.aspectRatio ?? DEFAULT_IMAGE_ASPECT_RATIO);
  const imageQuality = String(node.data.imageQuality ?? DEFAULT_IMAGE_QUALITY);
  const resolution = String(node.data.resolution ?? DEFAULT_IMAGE_RESOLUTION);

  return `${aspectRatio} · ${imageQuality} · ${resolution}`;
};

export const IMAGE_SLASH_COMMANDS: ImageSlashCommand[] = [
  {
    title: "多机位九宫格",
    description: "基于当前参考图生成九种机位方案。",
  },
  {
    title: "剧情推演四宫格",
    description: "向前推演一个情节动作，生成四格连续画面。",
  },
  {
    title: "25宫格连贯分镜",
    description: "把一个画面展开为连续分镜序列。",
  },
  {
    title: "电影级光影矫正",
    description: "优化画面光影、色彩、层次与电影感。",
  },
  {
    title: "角色三视图生成",
    description: "根据角色参考图生成正面、侧面、背面三视图。",
  },
  {
    title: "画面推演-3秒后",
    description: "推演当前画面三秒后的动作和构图。",
  },
  {
    title: "画面推演-5秒前",
    description: "反推当前画面五秒前的动作和构图。",
  },
];
