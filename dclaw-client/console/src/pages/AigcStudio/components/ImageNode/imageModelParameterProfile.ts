import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";

type ImageParameterProfileKind =
  | "full"
  | "seedream-4-5"
  | "nano2"
  | "mxapi-gpt-image-2";
export type ImagePromptToolKey = "style" | "mark" | "focus";

export type ImageModelParameterProfile = {
  kind: ImageParameterProfileKind;
  aspectRatios: string[];
  resolutions: string[];
  defaultAspectRatio: string;
  defaultResolution: string;
  defaultQuality: string;
  showQuality: boolean;
  showPanorama: boolean;
  showCamera: boolean;
  showAdvanced: boolean;
  promptTools: ImagePromptToolKey[];
  sizeFor: (resolution: string, aspectRatio: string) => string | undefined;
};

type ImageParameterSelection = {
  aspectRatio?: unknown;
  imageQuality?: unknown;
  resolution?: unknown;
};

const FULL_ASPECT_RATIOS = [
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

const FULL_RESOLUTIONS = ["1K", "2K", "4K"];
const FULL_QUALITY_OPTIONS = ["低画质", "标准画质", "高画质"];
const DEFAULT_ASPECT_RATIO = "16:9";
const DEFAULT_RESOLUTION = "2K";
const DEFAULT_QUALITY = "标准画质";

const SEEDREAM_45_ASPECT_RATIOS = [
  "1:1",
  "4:3",
  "3:4",
  "16:9",
  "9:16",
  "3:2",
  "2:3",
  "21:9",
  "9:21",
];

const SEEDREAM_45_SIZE_TABLE: Record<string, Record<string, string>> = {
  "2K": {
    "1:1": "2048x2048",
    "4:3": "2304x1728",
    "3:4": "1728x2304",
    "16:9": "2848x1600",
    "9:16": "1600x2848",
    "3:2": "2496x1664",
    "2:3": "1664x2496",
    "21:9": "3136x1344",
    "9:21": "1344x3136",
  },
  "4K": {
    "1:1": "4096x4096",
    "3:4": "3520x4704",
    "4:3": "4704x3520",
    "16:9": "5504x3040",
    "9:16": "3040x5504",
    "2:3": "3328x4992",
    "3:2": "4992x3328",
    "21:9": "6240x2656",
    "9:21": "2656x6240",
  },
};

const NANO2_ASPECT_RATIOS = ["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"];
const MXAPI_GPT_IMAGE_2_ASPECT_RATIOS = [
  "1:1",
  "3:2",
  "2:3",
  "4:3",
  "3:4",
  "16:9",
  "9:16",
  "21:9",
  "9:21",
  "3:1",
  "1:3",
];

const fullProfile: ImageModelParameterProfile = {
  kind: "full",
  aspectRatios: FULL_ASPECT_RATIOS,
  resolutions: FULL_RESOLUTIONS,
  defaultAspectRatio: DEFAULT_ASPECT_RATIO,
  defaultResolution: DEFAULT_RESOLUTION,
  defaultQuality: DEFAULT_QUALITY,
  showQuality: true,
  showPanorama: true,
  showCamera: true,
  showAdvanced: true,
  promptTools: ["style", "mark", "focus"],
  sizeFor: () => undefined,
};

const seedream45Profile: ImageModelParameterProfile = {
  kind: "seedream-4-5",
  aspectRatios: SEEDREAM_45_ASPECT_RATIOS,
  resolutions: ["2K", "4K"],
  defaultAspectRatio: DEFAULT_ASPECT_RATIO,
  defaultResolution: DEFAULT_RESOLUTION,
  defaultQuality: "",
  showQuality: false,
  showPanorama: false,
  showCamera: false,
  showAdvanced: false,
  promptTools: ["style"],
  sizeFor: (resolution, aspectRatio) =>
    SEEDREAM_45_SIZE_TABLE[resolution]?.[aspectRatio],
};

const nano2Profile: ImageModelParameterProfile = {
  kind: "nano2",
  aspectRatios: NANO2_ASPECT_RATIOS,
  resolutions: ["1K", "2K", "4K"],
  defaultAspectRatio: "1:1",
  defaultResolution: "1K",
  defaultQuality: "",
  showQuality: false,
  showPanorama: false,
  showCamera: false,
  showAdvanced: false,
  promptTools: ["style"],
  sizeFor: () => undefined,
};

const mxapiGptImage2Profile: ImageModelParameterProfile = {
  kind: "mxapi-gpt-image-2",
  aspectRatios: MXAPI_GPT_IMAGE_2_ASPECT_RATIOS,
  resolutions: ["1K", "2K", "4K"],
  defaultAspectRatio: "1:1",
  defaultResolution: "1K",
  defaultQuality: DEFAULT_QUALITY,
  showQuality: true,
  showPanorama: false,
  showCamera: false,
  showAdvanced: false,
  promptTools: ["style"],
  sizeFor: () => undefined,
};

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const normalizedToken = (value: unknown) =>
  textValue(value)
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");

export function imageModelParameterProfileFor(
  model?: AigcCapabilityInfo | null,
): ImageModelParameterProfile {
  const providerToken = normalizedToken(model?.provider_id);
  const modelToken = `${normalizedToken(model?.model_id)} ${normalizedToken(
    model?.model_name,
  )}`;
  if (modelToken.includes("seedream45")) return seedream45Profile;
  if (modelToken.includes("nano2") || modelToken.includes("nanobanana2")) {
    return nano2Profile;
  }
  if (providerToken === "mxapi" && modelToken.includes("gptimage2")) {
    return mxapiGptImage2Profile;
  }
  return fullProfile;
}

export function normalizedImageParameterSelection(
  profile: ImageModelParameterProfile,
  selection: ImageParameterSelection,
) {
  const rawAspectRatio = textValue(selection.aspectRatio);
  const rawResolution = textValue(selection.resolution);
  const rawQuality = textValue(selection.imageQuality);
  return {
    aspectRatio: profile.aspectRatios.includes(rawAspectRatio)
      ? rawAspectRatio
      : profile.defaultAspectRatio,
    imageQuality:
      profile.showQuality && FULL_QUALITY_OPTIONS.includes(rawQuality)
        ? rawQuality
        : profile.defaultQuality,
    resolution: profile.resolutions.includes(rawResolution)
      ? rawResolution
      : profile.defaultResolution,
  };
}

export function imageSizeParameterSummary(
  profile: ImageModelParameterProfile,
  selection: ReturnType<typeof normalizedImageParameterSelection>,
) {
  return profile.showQuality
    ? `${selection.aspectRatio} · ${selection.imageQuality} · ${selection.resolution}`
    : `${selection.aspectRatio} · ${selection.resolution}`;
}

export function imageGenerationParametersForProfile(
  profile: ImageModelParameterProfile,
  data: AigcCanvasNode["data"],
) {
  let parameters: Record<string, unknown>;
  if (
    profile.kind === "seedream-4-5" ||
    profile.kind === "nano2" ||
    profile.kind === "mxapi-gpt-image-2"
  ) {
    const selection = normalizedImageParameterSelection(profile, data);
    parameters = {
      imageMode: data.imageMode,
      aspectRatio: selection.aspectRatio,
      resolution: selection.resolution,
      imageCount: data.imageCount,
    };
    if (profile.showQuality) {
      parameters.imageQuality = selection.imageQuality;
    }
  } else {
    parameters = {
      imageMode: data.imageMode,
      panoramaMode: data.panoramaMode,
      aspectRatio: data.aspectRatio,
      imageQuality: data.imageQuality,
      resolution: data.resolution,
      imageCount: data.imageCount,
    };
    parameters.imageQuality = data.imageQuality;
    [
      "stylePreset",
      "markPreset",
      "focusPreset",
      "cameraProfile",
      "cameraBody",
      "lens",
      "focal",
      "aperture",
      "webSearch",
      "slashCommand",
      "upscaleProvider",
      "upscaleModel",
      "upscaleFactor",
    ].forEach((key) => {
      parameters[key] = data[key];
    });
  }
  return Object.fromEntries(
    Object.entries(parameters).filter(([, value]) => value !== undefined),
  );
}
