import {
  Grid,
  OrbitControls,
  PerspectiveCamera,
  useGLTF,
} from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import {
  Box,
  Camera,
  ExternalLink,
  Image,
  Images,
  Lightbulb,
  Save,
  Shapes,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import {
  Component,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  Box3,
  PerspectiveCamera as ThreePerspectiveCamera,
  Vector3,
} from "three";
import { clone as cloneSkeleton } from "three/examples/jsm/utils/SkeletonUtils.js";

import styles from "../../index.module.less";
import {
  AuthenticatedAssetImage,
  useAuthenticatedAssetSource,
} from "../AuthenticatedAssetImage";
import {
  DIRECTOR_STAGE_MANNEQUIN_MODEL_ID,
  DIRECTOR_STAGE_MANNEQUIN_MODEL_URL,
  directorStageAttributionsForProject,
  type DirectorStageCamera,
  type DirectorStageModelAsset,
  type DirectorStageObject,
  type DirectorStageObjectKind,
  type DirectorStagePoseId,
  type DirectorStageProject,
  type DirectorStageScenePresetId,
} from "./directorStageTypes";
import {
  addDirectorStageAsset,
  addUploadedDirectorStageModel,
  applyDirectorStageScenePreset,
  DIRECTOR_STAGE_ASSETS,
  DIRECTOR_STAGE_LIGHTING_PRESETS,
  DIRECTOR_STAGE_POSE_PRESETS,
  DIRECTOR_STAGE_PROP_BOX_ID,
  DIRECTOR_STAGE_PROP_CYLINDER_ID,
  DIRECTOR_STAGE_PROP_SPHERE_ID,
  DIRECTOR_STAGE_SCENE_PRESETS,
  directorStageLightingSetup,
} from "./directorStageCatalog";
import type { DirectorStageEditorProps } from "./types";

function nextId(prefix: string, count: number) {
  return `${prefix}-${count + 1}`;
}

function addCamera(project: DirectorStageProject): DirectorStageProject {
  const index = project.cameras.length + 1;
  const camera: DirectorStageCamera = {
    id: nextId("camera", project.cameras.length),
    name: `机位${String(index).padStart(2, "0")}`,
    position: [4 + index * 0.5, 2.5, 5],
    target: [0, 1, 0],
    fov: 45,
  };
  return {
    ...project,
    activeCameraId: camera.id,
    cameras: [...project.cameras, camera],
    updatedAt: new Date().toISOString(),
  };
}

const sanitizeCaptureName = (name: string) =>
  name.replace(/[\\/:*?"<>|]+/g, "-").trim();

const captureFileName = (name: string) => {
  const baseName = sanitizeCaptureName(name) || "导演台机位";
  return baseName.toLowerCase().endsWith(".png") ? baseName : `${baseName}.png`;
};

const captureBaseName = (name: string) =>
  sanitizeCaptureName(name).replace(/\.png$/i, "");

const numberInput = (value: string, fallback: number) => {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
};

function CaptureBridge({
  onReady,
}: {
  onReady: (capture: (camera?: DirectorStageCamera) => string | null) => void;
}) {
  const { gl, scene, size } = useThree();
  const captureCamera = useMemo(() => new ThreePerspectiveCamera(), []);

  useEffect(() => {
    onReady((camera) => {
      try {
        if (camera) {
          captureCamera.aspect = size.width / Math.max(1, size.height);
          captureCamera.fov = camera.fov;
          captureCamera.position.set(...camera.position);
          captureCamera.lookAt(...camera.target);
          captureCamera.updateProjectionMatrix();
          gl.render(scene, captureCamera);
        }
        return gl.domElement.toDataURL("image/png");
      } catch {
        return null;
      }
    });
  }, [captureCamera, gl, onReady, scene, size.height, size.width]);

  return null;
}

const MANNEQUIN_ROOT_POSES: Record<
  DirectorStagePoseId,
  {
    position: [number, number, number];
    rotation: [number, number, number];
  }
> = {
  neutral: { position: [0, 0, 0], rotation: [0, 0, 0] },
  conversation: { position: [0, 0, 0], rotation: [0, 0.08, 0.035] },
  wave: { position: [0, 0.015, 0], rotation: [0, -0.08, -0.035] },
  action: { position: [0, 0.04, 0], rotation: [0.04, 0.12, -0.1] },
};

function Mannequin() {
  const gltf = useGLTF(DIRECTOR_STAGE_MANNEQUIN_MODEL_URL);
  const scene = useMemo(() => cloneSkeleton(gltf.scene), [gltf.scene]);
  return (
    <group scale={0.01}>
      <primitive object={scene} />
    </group>
  );
}

function ProceduralCharacter({
  color = "#5fd4ff",
  poseId = "neutral",
}: {
  color?: string;
  poseId?: DirectorStagePoseId;
}) {
  const pose = {
    neutral: { leftArm: 0.08, rightArm: -0.08, body: 0 },
    conversation: { leftArm: -0.72, rightArm: 0.62, body: 0.04 },
    wave: { leftArm: 0.08, rightArm: -2.35, body: 0 },
    action: { leftArm: -0.95, rightArm: 0.88, body: -0.1 },
  }[poseId];
  return (
    <group rotation={[0, 0, pose.body]}>
      <mesh position={[0, 1.55, 0]}>
        <sphereGeometry args={[0.22, 24, 24]} />
        <meshStandardMaterial color={color} roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.92, 0]}>
        <capsuleGeometry args={[0.24, 0.72, 12, 24]} />
        <meshStandardMaterial color={color} roughness={0.76} />
      </mesh>
      <mesh position={[-0.42, 1.05, 0]} rotation={[0, 0, pose.leftArm]}>
        <capsuleGeometry args={[0.07, 0.62, 8, 16]} />
        <meshStandardMaterial color={color} roughness={0.76} />
      </mesh>
      <mesh position={[0.42, 1.05, 0]} rotation={[0, 0, pose.rightArm]}>
        <capsuleGeometry args={[0.07, 0.62, 8, 16]} />
        <meshStandardMaterial color={color} roughness={0.76} />
      </mesh>
      <mesh position={[-0.18, 0.28, 0]}>
        <capsuleGeometry args={[0.08, 0.52, 8, 16]} />
        <meshStandardMaterial color={color} roughness={0.76} />
      </mesh>
      <mesh position={[0.18, 0.28, 0]}>
        <capsuleGeometry args={[0.08, 0.52, 8, 16]} />
        <meshStandardMaterial color={color} roughness={0.76} />
      </mesh>
    </group>
  );
}

function ProceduralProp({
  color,
  modelId,
}: {
  color: string;
  modelId?: string;
}) {
  if (modelId === DIRECTOR_STAGE_PROP_CYLINDER_ID) {
    return (
      <mesh castShadow receiveShadow>
        <cylinderGeometry args={[0.62, 0.72, 1, 32]} />
        <meshStandardMaterial color={color} roughness={0.58} />
      </mesh>
    );
  }
  if (modelId === DIRECTOR_STAGE_PROP_SPHERE_ID) {
    return (
      <mesh castShadow receiveShadow>
        <sphereGeometry args={[0.72, 32, 24]} />
        <meshStandardMaterial color={color} roughness={0.52} />
      </mesh>
    );
  }
  return (
    <mesh castShadow receiveShadow>
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial color={color} roughness={0.58} />
    </mesh>
  );
}

class DirectorStageModelErrorBoundary extends Component<
  { fallback: ReactNode; modelUrl: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: Readonly<{ modelUrl: string }>) {
    if (previous.modelUrl !== this.props.modelUrl && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function UploadedModelPrimitive({
  kind,
  url,
}: {
  kind: DirectorStageObjectKind;
  url: string;
}) {
  const gltf = useGLTF(url);
  const normalized = useMemo(() => {
    const scene = cloneSkeleton(gltf.scene);
    scene.updateMatrixWorld(true);
    const bounds = new Box3().setFromObject(scene);
    if (bounds.isEmpty()) {
      return { scene, position: [0, 0, 0] as const, scale: 1 };
    }
    const size = bounds.getSize(new Vector3());
    const center = bounds.getCenter(new Vector3());
    const sourceSize =
      kind === "character"
        ? size.y
        : Math.max(size.x, size.y, size.z);
    const targetSize = kind === "character" ? 1.8 : 1.2;
    const scale = sourceSize > 0 ? targetSize / sourceSize : 1;
    scene.traverse((item) => {
      item.castShadow = true;
      item.receiveShadow = true;
    });
    return {
      scene,
      position: [
        -center.x * scale,
        -bounds.min.y * scale,
        -center.z * scale,
      ] as [number, number, number],
      scale,
    };
  }, [gltf.scene, kind]);

  return (
    <group position={normalized.position} scale={normalized.scale}>
      <primitive object={normalized.scene} />
    </group>
  );
}

function UploadedModelAsset({
  asset,
  color,
}: {
  asset: DirectorStageModelAsset;
  color?: string;
}) {
  const { loadState, needsAuthenticatedFetch, resolvedSrc } =
    useAuthenticatedAssetSource(asset.url, { preferProxy: true });
  const fallback =
    asset.kind === "character" ? (
      <ProceduralCharacter color={color} />
    ) : (
      <ProceduralProp color={color ?? "#f6c56f"} />
    );
  const ready = !needsAuthenticatedFetch || loadState === "loaded";
  if (!ready || loadState === "failed") return fallback;

  return (
    <DirectorStageModelErrorBoundary
      fallback={fallback}
      modelUrl={resolvedSrc}
    >
      <Suspense fallback={fallback}>
        <UploadedModelPrimitive kind={asset.kind} url={resolvedSrc} />
      </Suspense>
    </DirectorStageModelErrorBoundary>
  );
}

function StageObject({
  modelAsset,
  object,
  onSelect,
  selected,
}: {
  modelAsset?: DirectorStageModelAsset;
  object: DirectorStageObject;
  onSelect: (objectId: string) => void;
  selected: boolean;
}) {
  const transform = {
    position: object.position,
    rotation: object.rotation,
    scale: object.scale,
  } as const;
  const selectionMarker = selected ? (
    <mesh position={[0, 0.025, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[0.42, 0.5, 40]} />
      <meshBasicMaterial color="#35d3ff" depthTest={false} />
    </mesh>
  ) : null;

  if (object.kind === "character") {
    const poseId = object.poseId ?? "neutral";
    const mannequinRootPose = MANNEQUIN_ROOT_POSES[poseId];
    return (
      <group
        {...transform}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(object.id);
        }}
      >
        {selectionMarker}
        {modelAsset ? (
          <UploadedModelAsset asset={modelAsset} color={object.color} />
        ) : object.modelId === DIRECTOR_STAGE_MANNEQUIN_MODEL_ID ? (
          <Suspense
            fallback={
              <ProceduralCharacter color={object.color} poseId={poseId} />
            }
          >
            <group
              position={mannequinRootPose.position}
              rotation={mannequinRootPose.rotation}
            >
              <Mannequin />
            </group>
          </Suspense>
        ) : (
          <ProceduralCharacter color={object.color} poseId={poseId} />
        )}
      </group>
    );
  }

  return (
    <group
      {...transform}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(object.id);
      }}
    >
      {selectionMarker}
      {modelAsset ? (
        <UploadedModelAsset asset={modelAsset} color={object.color} />
      ) : (
        <ProceduralProp
          color={object.color ?? "#f6c56f"}
          modelId={object.modelId ?? DIRECTOR_STAGE_PROP_BOX_ID}
        />
      )}
    </group>
  );
}

function StageScene({
  onCaptureReady,
  onSelectObject,
  project,
  selectedObjectId,
}: {
  onCaptureReady: (
    capture: (camera?: DirectorStageCamera) => string | null,
  ) => void;
  onSelectObject: (objectId: string | null) => void;
  project: DirectorStageProject;
  selectedObjectId: string | null;
}) {
  const activeCamera =
    project.cameras.find((item) => item.id === project.activeCameraId) ??
    project.cameras[0];
  const lighting = directorStageLightingSetup(project.scene?.lightingPreset);

  return (
    <Canvas
      camera={{
        fov: activeCamera?.fov ?? 45,
        position: activeCamera?.position ?? [4, 3, 6],
      }}
      className={styles.directorStageCanvas}
      gl={{ preserveDrawingBuffer: true }}
      onPointerMissed={() => onSelectObject(null)}
      shadows
    >
      <color
        attach="background"
        args={[project.scene?.backgroundColor ?? "#101114"]}
      />
      <PerspectiveCamera
        makeDefault
        fov={activeCamera?.fov ?? 45}
        position={activeCamera?.position ?? [4, 3, 6]}
      />
      <ambientLight intensity={lighting.ambientIntensity} />
      <directionalLight
        castShadow
        color={lighting.keyColor}
        intensity={lighting.keyIntensity}
        position={lighting.keyPosition}
      />
      <pointLight
        color={lighting.fillColor}
        intensity={lighting.fillIntensity}
        position={lighting.fillPosition}
      />
      <Grid args={[18, 18]} cellColor="#3f4654" sectionColor="#6f7d92" />
      {project.objects.map((object) => (
        <StageObject
          key={object.id}
          modelAsset={(project.modelAssets ?? []).find(
            (item) => item.id === object.modelId,
          )}
          object={object}
          selected={object.id === selectedObjectId}
          onSelect={onSelectObject}
        />
      ))}
      <OrbitControls target={activeCamera?.target ?? [0, 1, 0]} />
      <CaptureBridge onReady={onCaptureReady} />
    </Canvas>
  );
}

function fallbackCaptureDataUrl() {
  if (typeof document !== "undefined") {
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    const context = canvas.getContext("2d");
    if (context) {
      context.fillStyle = "#101114";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "rgba(53, 211, 255, 0.82)";
      context.beginPath();
      context.arc(640, 300, 86, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = "rgba(246, 197, 111, 0.92)";
      context.roundRect(420, 430, 440, 58, 18);
      context.fill();
      return canvas.toDataURL("image/png");
    }
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#101114"/><circle cx="640" cy="300" r="86" fill="#35d3ff" opacity="0.8"/><rect x="420" y="430" width="440" height="58" rx="18" fill="#f6c56f" opacity="0.92"/></svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

function DirectorStageEditor({
  captures,
  initialProject,
  onCapture,
  onCaptureBatch,
  onClose,
  onSave,
  onUploadModel,
  sourcePreviewUrl,
}: DirectorStageEditorProps) {
  const [project, setProject] = useState<DirectorStageProject>(() => ({
    ...initialProject,
    scene: {
      ...initialProject.scene,
      sourceImageUrl:
        initialProject.scene?.sourceImageUrl ?? sourcePreviewUrl ?? null,
    },
  }));
  const [capture, setCapture] = useState<
    (camera?: DirectorStageCamera) => string | null
  >(() => () => null);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(
    initialProject.objects[0]?.id ?? null,
  );
  const [captureName, setCaptureName] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saved">("idle");
  const [captureState, setCaptureState] = useState<
    "idle" | "uploading" | "success" | "error"
  >("idle");
  const [captureMode, setCaptureMode] = useState<"single" | "batch">("single");
  const [captureMessage, setCaptureMessage] = useState("");
  const [modelKind, setModelKind] =
    useState<DirectorStageObjectKind>("character");
  const [modelUploadState, setModelUploadState] = useState<
    "idle" | "uploading" | "success" | "error"
  >("idle");
  const [modelUploadMessage, setModelUploadMessage] = useState("");
  const activeCamera =
    project.cameras.find((item) => item.id === project.activeCameraId) ??
    project.cameras[0];
  const selectedObject =
    project.objects.find((item) => item.id === selectedObjectId) ?? null;
  const modelAssets = project.modelAssets ?? [];
  const selectedModelAsset = modelAssets.find(
    (item) => item.id === selectedObject?.modelId,
  );
  const usedUploadedModels = modelAssets.filter((model) =>
    project.objects.some((object) => object.modelId === model.id),
  );
  const usedAttributions = directorStageAttributionsForProject(project);
  const captureUploading = captureState === "uploading";

  const markProjectDirty = useCallback(() => {
    setDirty(true);
    setSaveState("idle");
    setCaptureState("idle");
    setCaptureMessage("");
  }, []);

  const commitProject = useCallback(
    (nextProject: DirectorStageProject) => {
      setProject(nextProject);
      markProjectDirty();
    },
    [markProjectDirty],
  );

  const updateProject = useCallback(
    (updater: (current: DirectorStageProject) => DirectorStageProject) => {
      setProject((current) => updater(current));
      markProjectDirty();
    },
    [markProjectDirty],
  );

  useEffect(() => {
    if (
      selectedObjectId &&
      !project.objects.some((item) => item.id === selectedObjectId)
    ) {
      setSelectedObjectId(project.objects[0]?.id ?? null);
    }
  }, [project.objects, selectedObjectId]);

  const updateSelectedObject = useCallback(
    (updater: (object: DirectorStageObject) => DirectorStageObject) => {
      if (!selectedObjectId) return;
      updateProject((current) => ({
        ...current,
        objects: current.objects.map((item) =>
          item.id === selectedObjectId ? updater(item) : item,
        ),
        updatedAt: new Date().toISOString(),
      }));
    },
    [selectedObjectId, updateProject],
  );

  const updateActiveCamera = useCallback(
    (updater: (camera: DirectorStageCamera) => DirectorStageCamera) => {
      if (!activeCamera) return;
      updateProject((current) => ({
        ...current,
        cameras: current.cameras.map((item) =>
          item.id === activeCamera.id ? updater(item) : item,
        ),
        updatedAt: new Date().toISOString(),
      }));
    },
    [activeCamera, updateProject],
  );

  const handleAddAsset = (assetId: string) => {
    const nextProject = addDirectorStageAsset(project, assetId);
    commitProject(nextProject);
    setSelectedObjectId(
      nextProject.objects[nextProject.objects.length - 1]?.id ?? null,
    );
  };

  const handleAddUploadedModel = (model: DirectorStageModelAsset) => {
    const nextProject = addUploadedDirectorStageModel(project, model);
    commitProject(nextProject);
    setSelectedObjectId(
      nextProject.objects[nextProject.objects.length - 1]?.id ?? null,
    );
  };

  const handleModelUpload = async (file: File) => {
    if (modelUploadState === "uploading") return;
    setModelUploadState("uploading");
    setModelUploadMessage("");
    try {
      const result = await onUploadModel(file, modelKind);
      if (!result.ok) {
        setModelUploadState("error");
        setModelUploadMessage(result.error || "模型上传失败");
        return;
      }
      const nextProject = addUploadedDirectorStageModel(project, result.model);
      commitProject(nextProject);
      setSelectedObjectId(
        nextProject.objects[nextProject.objects.length - 1]?.id ?? null,
      );
      setModelUploadState("success");
      setModelUploadMessage(`${result.model.name} 已加入场景`);
    } catch (error) {
      setModelUploadState("error");
      setModelUploadMessage(
        error instanceof Error ? error.message : "模型上传失败",
      );
    }
  };

  const handleApplyScenePreset = (presetId: DirectorStageScenePresetId) => {
    if (
      project.objects.length > 0 &&
      typeof window !== "undefined" &&
      !window.confirm("应用场景模板将替换当前对象和机位，确定继续吗？")
    ) {
      return;
    }
    const nextProject = applyDirectorStageScenePreset(project, presetId);
    commitProject(nextProject);
    setSelectedObjectId(nextProject.objects[0]?.id ?? null);
  };

  const handleAddCamera = () => {
    commitProject(addCamera(project));
  };

  const handleSelectCamera = (cameraId: string) => {
    commitProject({
      ...project,
      activeCameraId: cameraId,
      updatedAt: new Date().toISOString(),
    });
  };

  const handleDeleteSelectedObject = () => {
    if (!selectedObjectId) return;
    const nextProject = {
      ...project,
      objects: project.objects.filter((item) => item.id !== selectedObjectId),
      updatedAt: new Date().toISOString(),
    };
    commitProject(nextProject);
    setSelectedObjectId(nextProject.objects[0]?.id ?? null);
  };

  const handleDeleteActiveCamera = () => {
    if (!activeCamera || project.cameras.length <= 1) return;
    const cameras = project.cameras.filter(
      (item) => item.id !== activeCamera.id,
    );
    commitProject({
      ...project,
      activeCameraId: cameras[0]?.id ?? null,
      cameras,
      updatedAt: new Date().toISOString(),
    });
  };

  const handleSave = () => {
    const nextProject = { ...project, updatedAt: new Date().toISOString() };
    setProject(nextProject);
    onSave(nextProject);
    setDirty(false);
    setSaveState("saved");
    setCaptureState("idle");
    setCaptureMessage("");
  };

  const handleCapture = async () => {
    if (captureUploading) return;
    const dataUrl = capture(activeCamera) ?? fallbackCaptureDataUrl();
    const nextProject = { ...project, updatedAt: new Date().toISOString() };
    const nextCaptureName =
      captureName.trim() || activeCamera?.name || "导演台机位";
    setProject(nextProject);
    setCaptureMode("single");
    setCaptureState("uploading");
    setCaptureMessage("");

    try {
      const result = await onCapture({
        dataUrl,
        fileName: captureFileName(nextCaptureName),
        project: nextProject,
      });
      if (result.ok) {
        setDirty(false);
        setSaveState("saved");
        setCaptureState("success");
        setCaptureMessage("截图已回流");
      } else {
        setDirty(true);
        setCaptureState("error");
        setCaptureMessage(result.error || "截图上传失败");
      }
    } catch (error) {
      setDirty(true);
      setCaptureState("error");
      setCaptureMessage(
        error instanceof Error ? error.message : "截图上传失败",
      );
    }
  };

  const handleCaptureBatch = async () => {
    if (captureUploading || !project.cameras.length) return;
    const nextProject = { ...project, updatedAt: new Date().toISOString() };
    const customBaseName = captureBaseName(captureName);
    const payloads = project.cameras.map((camera) => ({
      dataUrl: capture(camera) ?? fallbackCaptureDataUrl(),
      fileName: captureFileName(
        customBaseName ? `${customBaseName}-${camera.name}` : camera.name,
      ),
      project: nextProject,
    }));
    if (activeCamera) capture(activeCamera);
    setProject(nextProject);
    setCaptureMode("batch");
    setCaptureState("uploading");
    setCaptureMessage("");

    try {
      const result = await onCaptureBatch(payloads);
      if (result.ok) {
        setDirty(false);
        setSaveState("saved");
        setCaptureState("success");
        setCaptureMessage(`已回流 ${result.captures.length} 张机位截图`);
      } else {
        setDirty(true);
        setCaptureState("error");
        setCaptureMessage(result.error || "批量截图上传失败");
      }
    } catch (error) {
      setDirty(true);
      setCaptureState("error");
      setCaptureMessage(
        error instanceof Error ? error.message : "批量截图上传失败",
      );
    }
  };

  const handleCaptureReady = useCallback(
    (nextCapture: (camera?: DirectorStageCamera) => string | null) => {
      setCapture(() => nextCapture);
    },
    [],
  );

  const handleClose = () => {
    if (
      dirty &&
      typeof window !== "undefined" &&
      !window.confirm("当前场景有未保存更改，确定关闭吗？")
    ) {
      return;
    }
    onClose();
  };

  return (
    <div className={styles.directorStageEditor}>
      <aside className={styles.directorStageToolbar}>
        <section
          className={styles.directorStageToolSection}
          aria-label="内置资产"
        >
          <strong>
            <Shapes size={14} />
            资产
          </strong>
          <div className={styles.directorStageAssetList}>
            {DIRECTOR_STAGE_ASSETS.map((asset) => (
              <button
                key={asset.id}
                type="button"
                onClick={() => handleAddAsset(asset.id)}
              >
                {asset.kind === "character" ? (
                  <UserRound size={14} />
                ) : (
                  <Box size={14} />
                )}
                {asset.label}
              </button>
            ))}
          </div>
        </section>
        <section
          className={styles.directorStageToolSection}
          aria-label="用户模型"
        >
          <strong>
            <Upload size={14} />
            用户模型
          </strong>
          <label className={styles.directorStageField}>
            <span>模型类型</span>
            <select
              aria-label="模型类型"
              value={modelKind}
              onChange={(event) =>
                setModelKind(event.currentTarget.value as DirectorStageObjectKind)
              }
            >
              <option value="character">角色</option>
              <option value="prop">道具</option>
            </select>
          </label>
          <label
            className={styles.directorStageUploadButton}
            aria-disabled={modelUploadState === "uploading"}
            title="单文件 GLB，最大 100 MB"
          >
            <Upload size={14} />
            {modelUploadState === "uploading" ? "模型上传中" : "上传 GLB"}
            <input
              aria-label="上传 GLB 模型"
              accept=".glb,model/gltf-binary"
              disabled={modelUploadState === "uploading"}
              type="file"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                if (file) void handleModelUpload(file);
              }}
            />
          </label>
          {modelUploadMessage ? (
            <div
              className={`${styles.directorStageStatus} ${
                modelUploadState === "error"
                  ? styles.directorStageStatusError
                  : ""
              }`}
              role="status"
            >
              {modelUploadMessage}
            </div>
          ) : null}
          {modelAssets.length ? (
            <div className={styles.directorStageModelList}>
              {modelAssets.map((model) => (
                <button
                  key={model.id}
                  type="button"
                  aria-label={`添加用户模型 ${model.name}`}
                  title={model.fileName}
                  onClick={() => handleAddUploadedModel(model)}
                >
                  {model.kind === "character" ? (
                    <UserRound size={14} />
                  ) : (
                    <Box size={14} />
                  )}
                  <span>{model.name}</span>
                </button>
              ))}
            </div>
          ) : null}
        </section>
        <section
          className={styles.directorStageToolSection}
          aria-label="场景模板"
        >
          <strong>场景模板</strong>
          <div className={styles.directorStagePresetList}>
            {DIRECTOR_STAGE_SCENE_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => handleApplyScenePreset(preset.id)}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </section>
        <button type="button" onClick={handleAddCamera}>
          <Camera size={15} />
          添加机位
        </button>
        <label className={styles.directorStageField}>
          <span>截图名称</span>
          <input
            placeholder={activeCamera?.name ?? "导演台机位"}
            value={captureName}
            onChange={(event) => setCaptureName(event.currentTarget.value)}
          />
        </label>
        <button
          type="button"
          disabled={captureUploading}
          onClick={handleCapture}
        >
          <Image size={15} />
          {captureUploading && captureMode === "single"
            ? "截图上传中"
            : "机位截图"}
        </button>
        <button
          type="button"
          disabled={captureUploading || !project.cameras.length}
          onClick={handleCaptureBatch}
        >
          <Images size={15} />
          {captureUploading && captureMode === "batch"
            ? "批量截图上传中"
            : "全部机位截图"}
        </button>
        <button type="button" onClick={handleSave}>
          <Save size={15} />
          保存场景
        </button>
        <button type="button" onClick={handleClose}>
          <X size={15} />
          关闭
        </button>
        {saveState === "saved" || dirty || captureMessage ? (
          <div
            className={`${styles.directorStageStatus} ${
              captureState === "error" ? styles.directorStageStatusError : ""
            }`}
            role="status"
          >
            {captureMessage ||
              (saveState === "saved" ? "已保存" : "有未保存更改")}
          </div>
        ) : null}
      </aside>
      <main className={styles.directorStageViewport}>
        {sourcePreviewUrl ? (
          <img
            alt="导演台参考图"
            className={styles.directorStageReferenceImage}
            src={sourcePreviewUrl}
          />
        ) : null}
        <StageScene
          project={project}
          selectedObjectId={selectedObjectId}
          onCaptureReady={handleCaptureReady}
          onSelectObject={setSelectedObjectId}
        />
      </main>
      <aside className={styles.directorStageInspector}>
        <strong>{activeCamera?.name ?? "机位"}</strong>
        <span>
          角色{" "}
          {project.objects.filter((item) => item.kind === "character").length}
        </span>
        <span>
          道具 {project.objects.filter((item) => item.kind === "prop").length}
        </span>
        <span>机位 {project.cameras.length}</span>
        <span>截图 {captures.length}</span>
        <section className={styles.directorStagePanel} aria-label="场景灯光">
          <strong className={styles.directorStagePanelTitle}>
            <Lightbulb size={14} />
            场景灯光
          </strong>
          <label className={styles.directorStageField}>
            <span>背景颜色</span>
            <input
              type="color"
              value={project.scene?.backgroundColor ?? "#101114"}
              onChange={(event) => {
                const backgroundColor = event.currentTarget.value;
                updateProject((current) => ({
                  ...current,
                  scene: { ...current.scene, backgroundColor },
                  updatedAt: new Date().toISOString(),
                }));
              }}
            />
          </label>
          <div className={styles.directorStagePresetList}>
            {DIRECTOR_STAGE_LIGHTING_PRESETS.map((preset) => {
              const active =
                (project.scene?.lightingPreset ?? "studio") === preset.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  className={
                    active ? styles.directorStageButtonActive : undefined
                  }
                  aria-pressed={active}
                  onClick={() => {
                    updateProject((current) => ({
                      ...current,
                      scene: {
                        ...current.scene,
                        lightingPreset: preset.id,
                      },
                      updatedAt: new Date().toISOString(),
                    }));
                  }}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
        </section>
        <section className={styles.directorStagePanel} aria-label="机位列表">
          <strong>机位</strong>
          <div className={styles.directorStageCameraList}>
            {project.cameras.map((camera) => (
              <button
                key={camera.id}
                type="button"
                className={
                  camera.id === activeCamera?.id
                    ? styles.directorStageButtonActive
                    : undefined
                }
                aria-pressed={camera.id === activeCamera?.id}
                onClick={() => handleSelectCamera(camera.id)}
              >
                {camera.name}
              </button>
            ))}
          </div>
        </section>
        {activeCamera ? (
          <section className={styles.directorStagePanel} aria-label="机位设置">
            <strong>机位设置</strong>
            <label className={styles.directorStageField}>
              <span>机位名称</span>
              <input
                value={activeCamera.name}
                onChange={(event) => {
                  const nextName = event.currentTarget.value;
                  updateActiveCamera((camera) => ({
                    ...camera,
                    name: nextName,
                  }));
                }}
              />
            </label>
            <div className={styles.directorStageFormGrid}>
              {(["X", "Y", "Z"] as const).map((axis, index) => (
                <label key={axis} className={styles.directorStageField}>
                  <span>{`机位位置 ${axis}`}</span>
                  <input
                    step="0.1"
                    type="number"
                    value={activeCamera.position[index]}
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      updateActiveCamera((camera) => {
                        const position = [
                          ...camera.position,
                        ] as DirectorStageCamera["position"];
                        position[index] = numberInput(
                          nextValue,
                          camera.position[index],
                        );
                        return { ...camera, position };
                      });
                    }}
                  />
                </label>
              ))}
            </div>
            <div className={styles.directorStageFormGrid}>
              {(["X", "Y", "Z"] as const).map((axis, index) => (
                <label key={axis} className={styles.directorStageField}>
                  <span>{`目标 ${axis}`}</span>
                  <input
                    step="0.1"
                    type="number"
                    value={activeCamera.target[index]}
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      updateActiveCamera((camera) => {
                        const target = [
                          ...camera.target,
                        ] as DirectorStageCamera["target"];
                        target[index] = numberInput(
                          nextValue,
                          camera.target[index],
                        );
                        return { ...camera, target };
                      });
                    }}
                  />
                </label>
              ))}
            </div>
            <label className={styles.directorStageField}>
              <span>视场角</span>
              <input
                min="10"
                max="120"
                step="1"
                type="number"
                value={activeCamera.fov}
                onChange={(event) => {
                  const nextValue = event.currentTarget.value;
                  updateActiveCamera((camera) => ({
                    ...camera,
                    fov: Math.min(
                      120,
                      Math.max(10, numberInput(nextValue, camera.fov)),
                    ),
                  }));
                }}
              />
            </label>
            <button
              type="button"
              className={styles.directorStageDangerButton}
              disabled={project.cameras.length <= 1}
              onClick={handleDeleteActiveCamera}
            >
              <Trash2 size={14} />
              删除机位
            </button>
          </section>
        ) : null}
        <section className={styles.directorStagePanel} aria-label="对象列表">
          <strong>对象</strong>
          <div className={styles.directorStageObjectList}>
            {project.objects.map((object) => (
              <button
                key={object.id}
                type="button"
                className={
                  object.id === selectedObjectId
                    ? styles.directorStageButtonActive
                    : undefined
                }
                aria-pressed={object.id === selectedObjectId}
                onClick={() => setSelectedObjectId(object.id)}
              >
                {object.name}
              </button>
            ))}
          </div>
        </section>
        {selectedObject ? (
          <section className={styles.directorStagePanel} aria-label="对象设置">
            <strong>对象设置</strong>
            <label className={styles.directorStageField}>
              <span>名称</span>
              <input
                value={selectedObject.name}
                onChange={(event) => {
                  const nextName = event.currentTarget.value;
                  updateSelectedObject((object) => ({
                    ...object,
                    name: nextName,
                  }));
                }}
              />
            </label>
            <div className={styles.directorStageFormGrid}>
              {(["X", "Y", "Z"] as const).map((axis, index) => (
                <label key={axis} className={styles.directorStageField}>
                  <span>{`位置 ${axis}`}</span>
                  <input
                    step="0.1"
                    type="number"
                    value={selectedObject.position[index]}
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      updateSelectedObject((object) => {
                        const position = [
                          ...object.position,
                        ] as DirectorStageObject["position"];
                        position[index] = numberInput(
                          nextValue,
                          object.position[index],
                        );
                        return { ...object, position };
                      });
                    }}
                  />
                </label>
              ))}
            </div>
            <label className={styles.directorStageField}>
              <span>朝向</span>
              <input
                step="5"
                type="number"
                value={Math.round((selectedObject.rotation[1] * 180) / Math.PI)}
                onChange={(event) => {
                  const nextValue = event.currentTarget.value;
                  updateSelectedObject((object) => ({
                    ...object,
                    rotation: [
                      object.rotation[0],
                      (numberInput(nextValue, 0) * Math.PI) / 180,
                      object.rotation[2],
                    ],
                  }));
                }}
              />
            </label>
            <label className={styles.directorStageField}>
              <span>尺寸</span>
              <input
                min="0.1"
                step="0.1"
                type="number"
                value={selectedObject.scale[0]}
                onChange={(event) => {
                  const nextValue = event.currentTarget.value;
                  updateSelectedObject((object) => {
                    const scale = Math.max(
                      0.1,
                      numberInput(nextValue, object.scale[0]),
                    );
                    return { ...object, scale: [scale, scale, scale] };
                  });
                }}
              />
            </label>
            <label className={styles.directorStageField}>
              <span>颜色</span>
              <input
                type="color"
                value={selectedObject.color ?? "#f6c56f"}
                onChange={(event) => {
                  const nextColor = event.currentTarget.value;
                  updateSelectedObject((object) => ({
                    ...object,
                    color: nextColor,
                  }));
                }}
              />
            </label>
            {selectedObject.kind === "character" && !selectedModelAsset ? (
              <div className={styles.directorStageField}>
                <span>角色姿态</span>
                <div className={styles.directorStagePresetList}>
                  {DIRECTOR_STAGE_POSE_PRESETS.map((preset) => {
                    const active =
                      (selectedObject.poseId ?? "neutral") === preset.id;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        className={
                          active ? styles.directorStageButtonActive : undefined
                        }
                        aria-pressed={active}
                        onClick={() => {
                          updateSelectedObject((object) => ({
                            ...object,
                            poseId: preset.id,
                          }));
                        }}
                      >
                        {preset.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : selectedModelAsset?.kind === "character" ? (
              <span className={styles.directorStageEmptyText}>
                自定义角色暂不支持骨骼姿势
              </span>
            ) : null}
            <button
              type="button"
              className={styles.directorStageDangerButton}
              onClick={handleDeleteSelectedObject}
            >
              <Trash2 size={14} />
              删除对象
            </button>
          </section>
        ) : null}
        <section className={styles.directorStagePanel} aria-label="截图历史">
          <strong>截图历史</strong>
          {captures.length ? (
            <div className={styles.directorStageCaptureList}>
              {[...captures].reverse().map((item) => (
                <div key={item.id} className={styles.directorStageCaptureItem}>
                  <AuthenticatedAssetImage
                    src={item.previewUrl}
                    alt={item.name}
                  />
                  <span title={item.name}>{item.name}</span>
                </div>
              ))}
            </div>
          ) : (
            <span className={styles.directorStageEmptyText}>暂无截图</span>
          )}
        </section>
        <section className={styles.directorStagePanel} aria-label="模型授权">
          <strong>模型授权</strong>
          {usedAttributions.length || usedUploadedModels.length ? (
            <div className={styles.directorStageAttributionList}>
              {usedAttributions.map((attribution) => (
                <div
                  key={attribution.id}
                  className={styles.directorStageAttributionItem}
                >
                  <span>{attribution.title}</span>
                  <small>
                    {attribution.author} · {attribution.license}
                  </small>
                  <div className={styles.directorStageAttributionLinks}>
                    <a
                      href={attribution.source}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`${attribution.title} 来源`}
                    >
                      <ExternalLink size={13} />
                      来源
                    </a>
                    <a
                      href={attribution.licenseUrl}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`${attribution.title} 授权条款`}
                    >
                      授权条款
                    </a>
                  </div>
                </div>
              ))}
              {usedUploadedModels.map((model) => (
                <div
                  key={model.id}
                  className={styles.directorStageAttributionItem}
                >
                  <span>{model.name}</span>
                  <small>用户上传 · 授权由上传者确认</small>
                </div>
              ))}
            </div>
          ) : (
            <span className={styles.directorStageEmptyText}>
              当前仅使用程序化资产
            </span>
          )}
        </section>
      </aside>
    </div>
  );
}

export default DirectorStageEditor;
