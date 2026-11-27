import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";

export const DEFAULT_AUDIO_MODEL_LABEL = "音频生成";
export const DEFAULT_AUDIO_DURATION = 30;
export const DEFAULT_AUDIO_FORMAT = "wav";
export const DEFAULT_AUDIO_VOICE_ID = "girl";
export const DEFAULT_AUDIO_VOICE_NAME = "少女音色";

export const AUDIO_PAUSE_OPTIONS = [
  { label: "0.25s", token: "<#0.25#>" },
  { label: "0.5s", token: "<#0.5#>" },
  { label: "1.0s", token: "<#1.0#>" },
  { label: "1.5s", token: "<#1.5#>" },
  { label: "自定义", token: "<#0.25#>" },
];

export const AUDIO_FILLER_OPTIONS = [
  { label: "笑声", token: "(笑声)" },
  { label: "轻笑", token: "(轻笑)" },
  { label: "咳嗽", token: "(咳嗽)" },
  { label: "清嗓子", token: "(清嗓子)" },
  { label: "正常换气", token: "(正常换气)" },
  { label: "喘气", token: "(喘气)" },
];

export const AUDIO_VOICE_OPTIONS = [
  {
    id: "young_male",
    name: "青涩青年音色",
    locale: "中文(普通话)",
    gender: "Male",
  },
  {
    id: "elite_male",
    name: "精英青年音色",
    locale: "中文(普通话)",
    gender: "Male",
  },
  {
    id: "storyteller",
    name: "霸道青年音色",
    locale: "中文(普通话)",
    gender: "Male",
  },
  {
    id: "student",
    name: "青年大学生音色",
    locale: "中文(普通话)",
    gender: "Male",
  },
  {
    id: DEFAULT_AUDIO_VOICE_ID,
    name: DEFAULT_AUDIO_VOICE_NAME,
    locale: "中文(普通话)",
    gender: "Female",
  },
  { id: "mature", name: "御姐音色", locale: "中文(普通话)", gender: "Female" },
];

export const AUDIO_EFFECT_OPTIONS = [
  "无",
  "空旷回音",
  "礼堂广播",
  "电话失真",
  "电音",
];

export type AudioNodeState =
  | "empty"
  | "editing"
  | "generating"
  | "generated"
  | "failed";

const AUDIO_NODE_STATES = new Set<AudioNodeState>([
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
      stringValue(node.data.audioVoiceName) ||
      stringValue(node.data.audioPauseTag) ||
      stringValue(node.data.audioFillerTag) ||
      node.data.inputUpdated === true ||
      stringValue(node.data.previewKind),
  );

export const audioNodeStateFromNode = (
  node: AigcCanvasNode,
): AudioNodeState => {
  const explicitState = stringValue(node.data.audioState);
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
  if (AUDIO_NODE_STATES.has(explicitState as AudioNodeState)) {
    return explicitState as AudioNodeState;
  }
  if (hasOutputs(node)) return "generated";
  if (hasEditingInput(node)) return "editing";
  return "empty";
};
