import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";

export type VideoNodeState =
  | "empty"
  | "editing"
  | "generating"
  | "generated"
  | "failed";

const VIDEO_NODE_STATES = new Set<VideoNodeState>([
  "empty",
  "editing",
  "generating",
  "generated",
  "failed",
]);

const stringValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const hasOutputs = (node: AigcCanvasNode) =>
  Array.isArray(node.data.outputs) && node.data.outputs.length > 0;

const hasEditingInput = (node: AigcCanvasNode) =>
  Boolean(
    stringValue(node.data.text) ||
      stringValue(node.data.composerText) ||
      stringValue(node.data.lastRunPrompt) ||
      stringValue(node.data.referenceAssetName) ||
      stringValue(node.data.referencePreviewUrl) ||
      stringValue(node.data.videoAssetName) ||
      stringValue(node.data.videoPreviewUrl) ||
      node.data.referenceThumb === true ||
      node.data.inputUpdated === true ||
      stringValue(node.data.videoMode) ||
      stringValue(node.data.activeVideoTab) ||
      stringValue(node.data.previewKind),
  );

export const videoNodeStateFromNode = (
  node: AigcCanvasNode,
): VideoNodeState => {
  const explicitState = stringValue(node.data.videoState);
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
  if (VIDEO_NODE_STATES.has(explicitState as VideoNodeState)) {
    return explicitState as VideoNodeState;
  }
  if (hasOutputs(node)) return "generated";
  if (hasEditingInput(node)) return "editing";
  return "empty";
};

export const VIDEO_MOTION_PRESETS = [
  "固定镜头",
  "跟随拍摄",
  "盘旋抬升",
  "盘旋下降",
  "镜头上摇",
  "镜头下摇",
  "镜头左摇",
  "镜头右摇",
  "镜头上升",
  "镜头下降",
  "镜头左移",
  "镜头右移",
  "镜头前推",
  "镜头后移",
  "变焦推进",
  "变焦拉远",
  "柯克变焦",
  "环绕拍摄",
  "滚筒旋转",
  "第一视角",
  "无人机",
  "高空航拍",
  "手持拍摄",
];

export const VIDEO_EFFECT_PRESETS = [
  "小蜜蜂运镜",
  "穿云而入",
  "飞跃地平线",
  "逆转引力",
  "地球缩放",
  "环球缩放",
  "瞳孔推镜",
  "俯冲地球",
  "产品扫光",
  "普拉达换装",
  "多角度定点",
  "水下慢镜头",
  "试妆特写",
  "悬浮缓入",
  "微距推镜",
  "直升机揭幕",
];

export type VideoCharacterAsset = {
  id: string;
  name: string;
  kind: "real_person" | "image" | "video" | "audio";
  tone: "store" | "product" | "portrait" | "landscape";
};

export const VIDEO_CHARACTER_ASSETS: VideoCharacterAsset[] = [
  {
    id: "xiangzuoji-store",
    name: "湘左记门店",
    kind: "real_person",
    tone: "store",
  },
  {
    id: "xiangzuoji-packaging",
    name: "产品包装",
    kind: "image",
    tone: "product",
  },
  {
    id: "brand-host-1",
    name: "门店讲解员",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "brand-host-2",
    name: "顾客侧影",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "outdoor-host-1",
    name: "外景主持",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "profile-reference-1",
    name: "侧脸参考",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "hand-motion-1",
    name: "手部动作",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "child-actor-1",
    name: "儿童演员",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "senior-customer-1",
    name: "银发顾客",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "rider-actor-1",
    name: "骑手演员",
    kind: "real_person",
    tone: "portrait",
  },
  {
    id: "cashier-1",
    name: "收银员",
    kind: "real_person",
    tone: "store",
  },
  {
    id: "store-front-1",
    name: "街边门头",
    kind: "image",
    tone: "landscape",
  },
  {
    id: "product-closeup-1",
    name: "饮品特写",
    kind: "image",
    tone: "product",
  },
  {
    id: "walking-shot-1",
    name: "人物走位",
    kind: "video",
    tone: "store",
  },
  {
    id: "voice-tone-1",
    name: "品牌旁白",
    kind: "audio",
    tone: "product",
  },
];
