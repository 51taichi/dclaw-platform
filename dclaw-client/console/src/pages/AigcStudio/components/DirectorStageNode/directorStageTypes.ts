import type {
  AigcCanvas,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";

export type DirectorStageObjectKind = "character" | "prop";

export type DirectorStagePoseId =
  | "neutral"
  | "conversation"
  | "wave"
  | "action";

export type DirectorStageLightingPresetId =
  | "studio"
  | "soft"
  | "dramatic"
  | "night";

export type DirectorStageScenePresetId = "dialogue" | "product" | "performance";

export type DirectorStageObject = {
  id: string;
  kind: DirectorStageObjectKind;
  name: string;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  color?: string;
  modelId?: string;
  poseId?: DirectorStagePoseId;
};

export type DirectorStageModelAsset = {
  id: string;
  assetId: string;
  kind: DirectorStageObjectKind;
  name: string;
  fileName: string;
  url: string;
  assetPath?: string;
  mimeType?: string | null;
  size?: number;
  createdAt: number;
};

export type DirectorStageCamera = {
  id: string;
  name: string;
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
};

export type DirectorStageProject = {
  version: 1;
  scene?: {
    backgroundColor?: string;
    lightingPreset?: DirectorStageLightingPresetId;
    sourceImageUrl?: string | null;
  };
  modelAssets?: DirectorStageModelAsset[];
  objects: DirectorStageObject[];
  cameras: DirectorStageCamera[];
  activeCameraId?: string | null;
  updatedAt?: string;
};

export type DirectorStageCapture = {
  id: string;
  assetId: string;
  assetPath?: string;
  mimeType?: string | null;
  name: string;
  previewUrl: string;
  createdAt: number;
};

export type DirectorStageModelAttribution = {
  id: string;
  title: string;
  author: string;
  source: string;
  license: string;
  licenseUrl: string;
};

export const DIRECTOR_STAGE_MANNEQUIN_MODEL_ID = "ue-mannequin-retopology";
export const DIRECTOR_STAGE_MANNEQUIN_MODEL_URL =
  "/models/director-stage/ue-mannequin-retopology.glb";

export const DIRECTOR_STAGE_MODEL_ATTRIBUTIONS: DirectorStageModelAttribution[] =
  [
    {
      id: DIRECTOR_STAGE_MANNEQUIN_MODEL_ID,
      title: "UE Mannequin (Retopology)",
      author: "William Luque",
      source:
        "https://sketchfab.com/3d-models/ue-mannequin-retopology-5394d9f894374a2ab7c57a21929ce4c2",
      license: "Sketchfab Standard",
      licenseUrl: "https://sketchfab.com/licenses",
    },
  ];

export function directorStageAttributionsForProject(
  project: DirectorStageProject,
) {
  const modelIds = new Set(project.objects.map((item) => item.modelId));
  return DIRECTOR_STAGE_MODEL_ATTRIBUTIONS.filter((item) =>
    modelIds.has(item.id),
  );
}

export function createDefaultDirectorStageProject(
  sourceImageUrl?: string | null,
): DirectorStageProject {
  return {
    version: 1,
    scene: {
      backgroundColor: "#101114",
      lightingPreset: "studio",
      sourceImageUrl: sourceImageUrl || null,
    },
    modelAssets: [],
    objects: [],
    cameras: [
      {
        id: "camera-1",
        name: "机位01",
        position: [4, 3, 6],
        target: [0, 1, 0],
        fov: 45,
      },
    ],
    activeCameraId: "camera-1",
  };
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const isDirectorStageObjectKind = (
  value: unknown,
): value is DirectorStageObjectKind => value === "character" || value === "prop";

const directorStageModelAssetsFromValue = (
  value: unknown,
): DirectorStageModelAsset[] => {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = typeof item.id === "string" ? item.id.trim() : "";
    const assetId =
      typeof item.assetId === "string" ? item.assetId.trim() : "";
    const name = typeof item.name === "string" ? item.name.trim() : "";
    const fileName =
      typeof item.fileName === "string" ? item.fileName.trim() : "";
    const url = typeof item.url === "string" ? item.url.trim() : "";
    if (
      !id ||
      !assetId ||
      !name ||
      !fileName ||
      !url ||
      !isDirectorStageObjectKind(item.kind)
    ) {
      return [];
    }
    return [
      {
        id,
        assetId,
        kind: item.kind,
        name,
        fileName,
        url,
        assetPath:
          typeof item.assetPath === "string" ? item.assetPath : undefined,
        mimeType:
          typeof item.mimeType === "string" || item.mimeType === null
            ? item.mimeType
            : undefined,
        size:
          typeof item.size === "number" && Number.isFinite(item.size)
            ? item.size
            : undefined,
        createdAt:
          typeof item.createdAt === "number" && Number.isFinite(item.createdAt)
            ? item.createdAt
            : Date.now(),
      },
    ];
  });
};

export function directorStageProjectFromNode(
  node: AigcCanvasNode,
): DirectorStageProject | null {
  const value = node.data.directorStageProject;
  if (!isRecord(value) || value.version !== 1) return null;
  const objects = Array.isArray(value.objects)
    ? (value.objects as DirectorStageObject[])
    : [];
  const cameras = Array.isArray(value.cameras)
    ? (value.cameras as DirectorStageCamera[])
    : [];
  const scene = isRecord(value.scene) ? value.scene : null;
  const lightingPreset = scene?.lightingPreset;
  return {
    version: 1,
    scene: scene
      ? {
          backgroundColor:
            typeof scene.backgroundColor === "string"
              ? scene.backgroundColor
              : undefined,
          lightingPreset:
            lightingPreset === "studio" ||
            lightingPreset === "soft" ||
            lightingPreset === "dramatic" ||
            lightingPreset === "night"
              ? lightingPreset
              : "studio",
          sourceImageUrl:
            typeof scene.sourceImageUrl === "string"
              ? scene.sourceImageUrl
              : null,
        }
      : undefined,
    modelAssets: directorStageModelAssetsFromValue(value.modelAssets),
    objects,
    cameras,
    activeCameraId:
      typeof value.activeCameraId === "string" ? value.activeCameraId : null,
    updatedAt:
      typeof value.updatedAt === "string" ? value.updatedAt : undefined,
  };
}

export function directorStageCapturesFromNode(
  node: AigcCanvasNode,
): DirectorStageCapture[] {
  return Array.isArray(node.data.directorStageCaptures)
    ? (node.data.directorStageCaptures as DirectorStageCapture[])
    : [];
}

export function directorStageStats(node: AigcCanvasNode) {
  const project = directorStageProjectFromNode(node);
  const objects = project?.objects ?? [];
  return {
    project,
    characterCount: objects.filter((item) => item.kind === "character").length,
    propCount: objects.filter((item) => item.kind === "prop").length,
    cameraCount: project?.cameras.length ?? 0,
    captureCount: directorStageCapturesFromNode(node).length,
  };
}

const outputValue = (output: unknown, key: string) =>
  isRecord(output) ? output[key] : undefined;

const firstOutputPreview = (node: AigcCanvasNode) => {
  const outputs = Array.isArray(node.data.outputs) ? node.data.outputs : [];
  const first = outputs[0];
  return String(outputValue(first, "url") ?? outputValue(first, "path") ?? "");
};

const previewFromNode = (node: AigcCanvasNode) =>
  String(
    node.data.assetPreviewUrl ??
      node.data.previewUrl ??
      node.data.referencePreviewUrl ??
      node.data.sourceImageOutputPath ??
      firstOutputPreview(node) ??
      "",
  ).trim();

export function directorStageSourcePreviewUrl(
  canvas: AigcCanvas | null,
  node: AigcCanvasNode,
) {
  if (!canvas) return "";
  const sourceIds = canvas.edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => edge.source);
  for (const sourceId of sourceIds) {
    const sourceNode = canvas.nodes.find((item) => item.id === sourceId);
    if (!sourceNode) continue;
    const previewUrl = previewFromNode(sourceNode);
    if (previewUrl) return previewUrl;
  }
  return "";
}
