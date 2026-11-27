import {
  DIRECTOR_STAGE_MANNEQUIN_MODEL_ID,
  type DirectorStageCamera,
  type DirectorStageLightingPresetId,
  type DirectorStageModelAsset,
  type DirectorStageObject,
  type DirectorStageObjectKind,
  type DirectorStagePoseId,
  type DirectorStageProject,
  type DirectorStageScenePresetId,
} from "./directorStageTypes";

export const DIRECTOR_STAGE_BLOCKOUT_CHARACTER_ID =
  "procedural-blockout-character";
export const DIRECTOR_STAGE_PROP_BOX_ID = "procedural-box";
export const DIRECTOR_STAGE_PROP_CYLINDER_ID = "procedural-cylinder";
export const DIRECTOR_STAGE_PROP_SPHERE_ID = "procedural-sphere";

export type DirectorStageAssetDefinition = {
  id: string;
  kind: DirectorStageObjectKind;
  label: string;
  color: string;
  positionY: number;
  scale: number;
};

export const DIRECTOR_STAGE_ASSETS: DirectorStageAssetDefinition[] = [
  {
    id: DIRECTOR_STAGE_MANNEQUIN_MODEL_ID,
    kind: "character",
    label: "人台角色",
    color: "#5fd4ff",
    positionY: 0,
    scale: 1,
  },
  {
    id: DIRECTOR_STAGE_BLOCKOUT_CHARACTER_ID,
    kind: "character",
    label: "简模角色",
    color: "#a8b5c7",
    positionY: 0,
    scale: 1,
  },
  {
    id: DIRECTOR_STAGE_PROP_BOX_ID,
    kind: "prop",
    label: "方箱",
    color: "#f6c56f",
    positionY: 0.35,
    scale: 0.7,
  },
  {
    id: DIRECTOR_STAGE_PROP_CYLINDER_ID,
    kind: "prop",
    label: "圆柱",
    color: "#8ed6c4",
    positionY: 0.5,
    scale: 0.7,
  },
  {
    id: DIRECTOR_STAGE_PROP_SPHERE_ID,
    kind: "prop",
    label: "球体",
    color: "#f19bb4",
    positionY: 0.55,
    scale: 0.65,
  },
];

export const DIRECTOR_STAGE_POSE_PRESETS: Array<{
  id: DirectorStagePoseId;
  label: string;
}> = [
  { id: "neutral", label: "自然站立" },
  { id: "conversation", label: "交谈" },
  { id: "wave", label: "挥手" },
  { id: "action", label: "动作" },
];

export type DirectorStageLightingSetup = {
  id: DirectorStageLightingPresetId;
  label: string;
  ambientIntensity: number;
  keyColor: string;
  keyIntensity: number;
  keyPosition: [number, number, number];
  fillColor: string;
  fillIntensity: number;
  fillPosition: [number, number, number];
};

export const DIRECTOR_STAGE_LIGHTING_PRESETS: DirectorStageLightingSetup[] = [
  {
    id: "studio",
    label: "棚拍",
    ambientIntensity: 0.72,
    keyColor: "#fff4df",
    keyIntensity: 1.3,
    keyPosition: [4, 6, 5],
    fillColor: "#b6dfff",
    fillIntensity: 0.48,
    fillPosition: [-4, 3, 2],
  },
  {
    id: "soft",
    label: "柔光",
    ambientIntensity: 1.05,
    keyColor: "#fff8ef",
    keyIntensity: 0.82,
    keyPosition: [3, 5, 4],
    fillColor: "#d8edff",
    fillIntensity: 0.62,
    fillPosition: [-3, 4, 3],
  },
  {
    id: "dramatic",
    label: "戏剧",
    ambientIntensity: 0.3,
    keyColor: "#ffd39a",
    keyIntensity: 2.1,
    keyPosition: [5, 7, 2],
    fillColor: "#4e8dff",
    fillIntensity: 1.05,
    fillPosition: [-4, 2, -3],
  },
  {
    id: "night",
    label: "夜景",
    ambientIntensity: 0.2,
    keyColor: "#92b9ff",
    keyIntensity: 1.45,
    keyPosition: [2, 6, 4],
    fillColor: "#ff7e9e",
    fillIntensity: 0.72,
    fillPosition: [-4, 2, -2],
  },
];

export const DIRECTOR_STAGE_SCENE_PRESETS: Array<{
  id: DirectorStageScenePresetId;
  label: string;
}> = [
  { id: "dialogue", label: "双人对话" },
  { id: "product", label: "产品展示" },
  { id: "performance", label: "单人表演" },
];

const nextAvailableId = (project: DirectorStageProject, prefix: string) => {
  let index = 1;
  while (project.objects.some((item) => item.id === `${prefix}-${index}`)) {
    index += 1;
  }
  return `${prefix}-${index}`;
};

export function addDirectorStageAsset(
  project: DirectorStageProject,
  assetId: string,
): DirectorStageProject {
  const asset = DIRECTOR_STAGE_ASSETS.find((item) => item.id === assetId);
  if (!asset) return project;
  const kindIndex =
    project.objects.filter((item) => item.kind === asset.kind).length + 1;
  const object: DirectorStageObject = {
    id: nextAvailableId(project, asset.kind),
    kind: asset.kind,
    name: `${asset.kind === "character" ? "角色" : "道具"}${String(
      kindIndex,
    ).padStart(2, "0")}`,
    position:
      asset.kind === "character"
        ? [kindIndex * 0.8 - 0.8, asset.positionY, 0]
        : [kindIndex * 0.8, asset.positionY, -1],
    rotation: [0, 0, 0],
    scale: [asset.scale, asset.scale, asset.scale],
    color: asset.color,
    modelId: asset.id,
    poseId: asset.kind === "character" ? "neutral" : undefined,
  };
  return {
    ...project,
    objects: [...project.objects, object],
    updatedAt: new Date().toISOString(),
  };
}

export function addUploadedDirectorStageModel(
  project: DirectorStageProject,
  model: DirectorStageModelAsset,
): DirectorStageProject {
  const kindIndex =
    project.objects.filter((item) => item.kind === model.kind).length + 1;
  const object: DirectorStageObject = {
    id: nextAvailableId(project, model.kind),
    kind: model.kind,
    name: model.name,
    position:
      model.kind === "character"
        ? [kindIndex * 0.8 - 0.8, 0, 0]
        : [kindIndex * 0.8, 0, -1],
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    modelId: model.id,
    poseId: model.kind === "character" ? "neutral" : undefined,
  };
  const modelAssets = project.modelAssets ?? [];
  return {
    ...project,
    modelAssets: modelAssets.some((item) => item.id === model.id)
      ? modelAssets
      : [...modelAssets, model],
    objects: [...project.objects, object],
    updatedAt: new Date().toISOString(),
  };
}

const camera = (
  id: string,
  name: string,
  position: DirectorStageCamera["position"],
  target: DirectorStageCamera["target"],
  fov: number,
): DirectorStageCamera => ({ id, name, position, target, fov });

const assetObject = (
  id: string,
  kind: DirectorStageObjectKind,
  name: string,
  modelId: string,
  position: DirectorStageObject["position"],
  rotation: DirectorStageObject["rotation"],
  scale: number,
  color: string,
  poseId?: DirectorStagePoseId,
): DirectorStageObject => ({
  id,
  kind,
  name,
  modelId,
  position,
  rotation,
  scale: [scale, scale, scale],
  color,
  poseId,
});

export function applyDirectorStageScenePreset(
  project: DirectorStageProject,
  presetId: DirectorStageScenePresetId,
): DirectorStageProject {
  const sourceImageUrl = project.scene?.sourceImageUrl ?? null;
  const updatedAt = new Date().toISOString();

  if (presetId === "product") {
    return {
      version: 1,
      scene: {
        backgroundColor: "#13161b",
        lightingPreset: "studio",
        sourceImageUrl,
      },
      modelAssets: project.modelAssets ?? [],
      objects: [
        assetObject(
          "prop-1",
          "prop",
          "主展示体",
          DIRECTOR_STAGE_PROP_BOX_ID,
          [0, 0.55, 0],
          [0, Math.PI / 6, 0],
          1.1,
          "#f6c56f",
        ),
        assetObject(
          "prop-2",
          "prop",
          "展示台",
          DIRECTOR_STAGE_PROP_CYLINDER_ID,
          [0, 0.18, 0],
          [0, 0, 0],
          1.45,
          "#67788d",
        ),
      ],
      cameras: [
        camera("camera-1", "主视觉", [4.2, 2.8, 5.8], [0, 0.8, 0], 42),
        camera("camera-2", "产品近景", [2.4, 1.7, 3.2], [0, 0.75, 0], 36),
        camera("camera-3", "俯拍", [0.1, 5.8, 2.1], [0, 0.4, 0], 48),
      ],
      activeCameraId: "camera-1",
      updatedAt,
    };
  }

  if (presetId === "performance") {
    return {
      version: 1,
      scene: {
        backgroundColor: "#0b1020",
        lightingPreset: "dramatic",
        sourceImageUrl,
      },
      modelAssets: project.modelAssets ?? [],
      objects: [
        assetObject(
          "character-1",
          "character",
          "表演者",
          DIRECTOR_STAGE_BLOCKOUT_CHARACTER_ID,
          [0, 0, 0],
          [0, 0, 0],
          1,
          "#8fb8ff",
          "action",
        ),
      ],
      cameras: [
        camera("camera-1", "全景", [4.8, 3.1, 6.7], [0, 1, 0], 48),
        camera("camera-2", "中景", [3.2, 2.1, 4.3], [0, 1.1, 0], 38),
        camera("camera-3", "低机位", [3.4, 0.85, 4.7], [0, 1.2, 0], 44),
      ],
      activeCameraId: "camera-1",
      updatedAt,
    };
  }

  return {
    version: 1,
    scene: {
      backgroundColor: "#11151a",
      lightingPreset: "soft",
      sourceImageUrl,
    },
    modelAssets: project.modelAssets ?? [],
    objects: [
      assetObject(
        "character-1",
        "character",
        "角色01",
        DIRECTOR_STAGE_MANNEQUIN_MODEL_ID,
        [-0.9, 0, 0],
        [0, Math.PI / 8, 0],
        1,
        "#5fd4ff",
        "conversation",
      ),
      assetObject(
        "character-2",
        "character",
        "角色02",
        DIRECTOR_STAGE_BLOCKOUT_CHARACTER_ID,
        [0.9, 0, 0],
        [0, -Math.PI / 8, 0],
        1,
        "#b8c4d6",
        "conversation",
      ),
    ],
    cameras: [
      camera("camera-1", "双人全景", [4.5, 2.7, 6.4], [0, 1, 0], 46),
      camera("camera-2", "角色01近景", [2.2, 1.8, 3.4], [-0.8, 1.2, 0], 34),
      camera("camera-3", "角色02近景", [-2.2, 1.8, 3.4], [0.8, 1.2, 0], 34),
    ],
    activeCameraId: "camera-1",
    updatedAt,
  };
}

export function directorStageLightingSetup(
  presetId?: DirectorStageLightingPresetId,
) {
  return (
    DIRECTOR_STAGE_LIGHTING_PRESETS.find((item) => item.id === presetId) ??
    DIRECTOR_STAGE_LIGHTING_PRESETS[0]!
  );
}
