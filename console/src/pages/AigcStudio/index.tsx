import { submitGuidedTaskAsset } from "./guidedTaskActions";
import { useGuidedTaskReturn } from "./useGuidedTaskReturn";
import {
  type CSSProperties,
  type ChangeEvent as ReactChangeEvent,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
  type WheelEvent as ReactWheelEvent,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Button,
  Empty,
  Input,
  Select,
  Spin,
  Modal,
  message as antdMessage,
} from "antd";
import {
  AlertCircle,
  Boxes,
  ChevronDown,
  CheckCircle2,
  Clipboard,
  Copy,
  Loader2,
  Maximize2,
  MousePointer2,
  Package,
  Play,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  aigcStudioApi,
  type AigcAsset,
  type AigcCanvas,
  type AigcCanvasEdge,
  type AigcCanvasNode,
} from "../../api/modules/aigcStudio";
import { createAssetPreviewUrl, type CanvasPoint } from "./canvasAssetFactory";
import {
  canvasHandleCenterKey,
  nodeHandleCenterSurfacePoint,
  type CanvasHandleCenters,
} from "./canvasHandleGeometry";
import {
  JOB_STATUS_FALLBACKS,
  assetPreviewSource,
  canvasAssetFromNode,
  nodeOutputs,
  nodeVisualHeight,
  nodeVisualWidth,
  shouldRenderNodeOutputList,
  translatedCapability,
  translatedNodeType,
  type CanvasAssetRecord,
} from "./canvasNodeUtils";
import {
  createNodeForType,
  createTemplateParts,
} from "./canvasTemplateFactory";
import {
  appendPortNode,
  appendTemplateParts,
  createPortEdge,
  portNodePosition,
  repositionTemplateNodes,
} from "./canvasTemplateActions";
import {
  downstreamDataFromSource,
  edgeRoleForSource,
  nodeDataForContextTarget,
} from "./canvasPortMapping";
import {
  boundedViewportScale,
  buildCanvasEdgeLines,
  centerViewportOnNode as centerCanvasViewportOnNode,
  defaultNodePositionInViewport,
  fitViewportToNodes as fitCanvasViewportToNodes,
  surfacePointToCanvasPoint,
  zoomViewportAroundSurfacePoint,
} from "./canvasGeometry";
import {
  dragNodePosition,
  isCanvasViewportTarget,
  offsetCanvasViewport,
  panCanvasViewport,
  type CanvasNodeDragState,
  type CanvasPanState,
} from "./canvasInteraction";
import {
  deleteCanvasNode,
  duplicateCanvasNodeWithEdges,
  pasteCanvasNode,
  restoreDeletedCanvasNode,
  type DeletedNodeSnapshot,
} from "./canvasCommands";
import {
  createCanvasProject,
  deleteCanvasProject,
  selectCanvasProject,
} from "./canvasProjectActions";
import {
  applyFinishedJobToCanvas,
  buildRunNodeJobRequest,
  imageReferenceAssetsForNode,
  prependCanvasJob,
  replaceCanvasJob,
  videoConnectedInputsForNode,
} from "./canvasJobActions";
import {
  appendCanvasNodes,
  buildUploadedAssetNodes,
  createAssetNodeFromRecord,
  defaultAssetNodePosition,
  filterCanvasAssetFiles,
  replaceSourceImageReferences,
} from "./canvasAssetActions";
import {
  applyPortConnectionToCanvas,
  applyPortDisconnectionToCanvas,
  cleanTargetDataForRemovedEdges,
} from "./canvasConnectionActions";
import {
  createImageAnnotationCanvas,
  imageAnnotationSourcePreviewUrl,
  type ImageAnnotationPath,
} from "./canvasAnnotationActions";
import { useCanvasFloatingMenus } from "./useCanvasFloatingMenus";
import { useCanvasPersistence } from "./useCanvasPersistence";
import { isScriptSourceTextNode } from "./utils/textNode";
import { AudioComposer } from "./components/AudioNode/AudioComposer";
import { AudioNode } from "./components/AudioNode/AudioNode";
import { useAudioNodeWorkflow } from "./components/AudioNode/useAudioNodeWorkflow";
import { ReferenceNoteNode } from "./components/AssetNode/ReferenceNoteNode";
import { UploadedAssetNode } from "./components/AssetNode/UploadedAssetNode";
import { CanvasEdgeLayer } from "./components/CanvasEdgeLayer/CanvasEdgeLayer";
import { CanvasMinimap } from "./components/CanvasMinimap/CanvasMinimap";
import { CanvasAddMenu } from "./components/CanvasMenus/CanvasAddMenu";
import { CanvasContextMenu } from "./components/CanvasMenus/CanvasContextMenu";
import { CanvasEmptyProjectLauncher } from "./components/CanvasMenus/CanvasEmptyProjectLauncher";
import { CanvasPortMenu } from "./components/CanvasMenus/CanvasPortMenu";
import { CanvasQuickTemplateMenu } from "./components/CanvasMenus/CanvasQuickTemplateMenu";
import { CanvasTemplateLauncher } from "./components/CanvasMenus/CanvasTemplateLauncher";
import { CanvasNodeHandle } from "./components/CanvasNodeHandle/CanvasNodeHandle";
import { CanvasRail, type RailPanel } from "./components/CanvasRail/CanvasRail";
import { CanvasRailPanel } from "./components/CanvasRail/CanvasRailPanel";
import { AuthenticatedAssetImage } from "./components/AuthenticatedAssetImage";
import { DirectorStageNode } from "./components/DirectorStageNode/DirectorStageNode";
import { directorStageSourcePreviewUrl } from "./components/DirectorStageNode/directorStageTypes";
import { useDirectorStageWorkflow } from "./components/DirectorStageNode/useDirectorStageWorkflow";
import { GenericNode } from "./components/GenericNode/GenericNode";
import { ImageCaptureGroupNode } from "./components/ImageNode/ImageCaptureGroupNode";
import { ImageAnnotationEditor } from "./components/ImageNode/ImageAnnotationEditor";
import { ImageComposer } from "./components/ImageNode/ImageComposer";
import { ImageNode } from "./components/ImageNode/ImageNode";
import type { ImageComposerMenu } from "./components/ImageNode/types";
import { useImageNodeWorkflow } from "./components/ImageNode/useImageNodeWorkflow";
import { LongImageExportNode } from "./components/LongImageExportNode/LongImageExportNode";
import { canRenderTextNode, TextNode } from "./components/TextNode/TextNode";
import { useTextNodeWorkflow } from "./components/TextNode/useTextNodeWorkflow";
import { ScriptComposer } from "./components/ScriptNode/ScriptComposer";
import { ScriptAssetGroupNode } from "./components/ScriptNode/ScriptAssetGroupNode";
import { ScriptNode } from "./components/ScriptNode/ScriptNode";
import {
  isStoryboardImageNode,
  scriptMode,
  storyboardImageMode,
} from "./components/ScriptNode/scriptNodeState";
import { useScriptNodeWorkflow } from "./components/ScriptNode/useScriptNodeWorkflow";
import { StoryboardComposer } from "./components/StoryboardWorkflow/StoryboardComposer";
import { StoryboardImageNode } from "./components/StoryboardWorkflow/StoryboardImageNode";
import { StoryboardVideoBatchNode } from "./components/StoryboardWorkflow/StoryboardVideoBatchNode";
import { StoryboardVideoComposer } from "./components/StoryboardWorkflow/StoryboardVideoComposer";
import { useStoryboardWorkflow } from "./components/StoryboardWorkflow/useStoryboardWorkflow";
import { VideoComposer } from "./components/VideoNode/VideoComposer";
import { VideoNode } from "./components/VideoNode/VideoNode";
import type { VideoComposerMenu } from "./components/VideoNode/types";
import { useVideoNodeWorkflow } from "./components/VideoNode/useVideoNodeWorkflow";
import {
  NODE_DEFINITIONS,
  capabilityForNode,
  isSidebarNodeType,
  isWorkflowOnlyNodeType,
  nodeDefinition,
  nodeIcon,
  type PortSide,
  type TemplateVariant,
} from "./domain/componentRegistry";
import {
  effectiveDefaultForCapability,
  modelForNode,
  modelKey,
  modelLabelForNode,
  modelOptionsForNode,
  modelSelectionState,
} from "./nodeModelSelection";
import { useGenerationProgressSimulation } from "./useGenerationProgressSimulation";
import styles from "./index.module.less";
import { AigcGuidePanel } from "./components/GuidePanel/AigcGuidePanel";
import { LegacyAigcGuidePanel } from "./components/GuidePanel/LegacyAigcGuidePanel";
import { getAigcGuideStepCompletion } from "./components/GuidePanel/guideStepCompletion";
import { useAigcGuideTask } from "./components/GuidePanel/useAigcGuideTask";
import { focusPlatformControl } from "./components/GuidePanel/controlRegistry";
import { superExpertPlatformApi } from "../../api/modules/superExpertPlatform";
import {
  resolveWorkflowOutputAssetId,
  resolveWorkflowReviewAssets,
} from "./workflowOutput";

function connectCanvasNodes(source: string, target: string): AigcCanvasEdge {
  return {
    id: `edge-${source}-${target}`,
    source,
    target,
    sourceHandle: "right",
    targetHandle: "left",
  };
}

type CanvasPortDragState = {
  nodeId: string;
  side: PortSide;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  hasMoved: boolean;
};

function buildSurfaceEdgePath(start: CanvasPoint, end: CanvasPoint): string {
  const horizontalDistance = Math.abs(end.x - start.x);
  const curve = Math.min(180, Math.max(64, horizontalDistance * 0.42));
  const direction = end.x >= start.x ? 1 : -1;
  return `M ${start.x} ${start.y} C ${start.x + curve * direction} ${
    start.y
  }, ${end.x - curve * direction} ${end.y}, ${end.x} ${end.y}`;
}

const sameHandleCenters = (
  left: CanvasHandleCenters,
  right: CanvasHandleCenters,
) => {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => {
    const leftPoint = left[key];
    const rightPoint = right[key];
    return leftPoint?.x === rightPoint?.x && leftPoint?.y === rightPoint?.y;
  });
};

const waitForCanvasFeedbackFrame = () =>
  new Promise<void>((resolve) => {
    if (typeof window === "undefined") {
      resolve();
      return;
    }
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => resolve());
      return;
    }
    window.setTimeout(resolve, 0);
  });

const isMultiImageResultsNode = (node: AigcCanvasNode) =>
  node.type === "image_generate" && nodeOutputs(node).length > 1;

const isExpandedImageResultsNode = (node: AigcCanvasNode) =>
  isMultiImageResultsNode(node) && node.data.imageResultsExpanded === true;

const IMAGE_RESULTS_GALLERY_GAP = 12;
const IMAGE_RESULTS_VIEWPORT_PADDING = 24;

const compactImageResultsNode = (node: AigcCanvasNode): AigcCanvasNode => ({
  ...node,
  data: {
    ...node.data,
    imageResultsExpanded: false,
  },
});

const clampNumber = (value: number, min: number, max: number) => {
  if (max < min) return min;
  return Math.min(max, Math.max(min, value));
};

type ImageResultsExpansionLayout = {
  primaryWidth: number;
  galleryWidth: number;
  galleryHeight: number;
  galleryLeft: number;
  galleryTop: number;
  galleryColumns: number;
  sideCount: number;
  placement: string;
};

const finiteNodeNumber = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const savedImageResultsExpansionLayout = (
  node: AigcCanvasNode,
): ImageResultsExpansionLayout | null => {
  const primaryWidth = finiteNodeNumber(node.data.imageResultsPrimaryWidth);
  const galleryWidth = finiteNodeNumber(node.data.imageResultsGalleryWidth);
  const galleryHeight = finiteNodeNumber(node.data.imageResultsGalleryHeight);
  const galleryLeft = finiteNodeNumber(node.data.imageResultsGalleryLeft);
  const galleryTop = finiteNodeNumber(node.data.imageResultsGalleryTop);
  const galleryColumns = finiteNodeNumber(node.data.imageResultsGalleryColumns);
  if (
    primaryWidth === null ||
    galleryWidth === null ||
    galleryHeight === null ||
    galleryLeft === null ||
    galleryTop === null ||
    galleryColumns === null
  ) {
    return null;
  }
  return {
    primaryWidth,
    galleryWidth,
    galleryHeight,
    galleryLeft,
    galleryTop,
    galleryColumns,
    sideCount: Math.max(1, nodeOutputs(node).length - 1),
    placement:
      typeof node.data.imageResultsGalleryPlacement === "string"
        ? node.data.imageResultsGalleryPlacement
        : "right",
  };
};

const imageResultsExpansionLayout = (
  node: AigcCanvasNode,
  layout: {
    viewport: AigcCanvas["viewport"] | undefined;
    viewportScale: number;
    visibleWidth: number;
    visibleHeight: number;
  },
): ImageResultsExpansionLayout | null => {
  if (!isMultiImageResultsNode(node)) return null;
  const compactNode = compactImageResultsNode(node);
  const primaryWidth = nodeVisualWidth(compactNode);
  const primaryHeight = nodeVisualHeight(compactNode);
  const outputCount = nodeOutputs(node).length;
  const sideCount = Math.max(1, outputCount - 1);
  const sideColumns = sideCount <= 1 ? 1 : 2;
  const galleryWidth = primaryWidth;
  const galleryHeight = primaryHeight;
  const scale = Math.max(0.1, layout.viewportScale || 1);
  const viewport = layout.viewport ?? { x: 0, y: 0, zoom: scale };
  const nodeLeft = viewport.x + node.position.x * scale;
  const nodeTop = viewport.y + node.position.y * scale;
  const scaledPrimaryWidth = primaryWidth * scale;
  const scaledPrimaryHeight = primaryHeight * scale;
  const scaledGalleryWidth = galleryWidth * scale;
  const scaledGalleryHeight = galleryHeight * scale;
  const scaledGap = IMAGE_RESULTS_GALLERY_GAP * scale;
  const padding = IMAGE_RESULTS_VIEWPORT_PADDING;
  const inlineLeft = clampNumber(
    0,
    (padding - nodeLeft) / scale,
    (layout.visibleWidth - padding - nodeLeft - scaledGalleryWidth) / scale,
  );
  const fitsRight =
    nodeLeft + scaledPrimaryWidth + scaledGap + scaledGalleryWidth <=
    layout.visibleWidth - padding;
  const fitsLeft = nodeLeft - scaledGap - scaledGalleryWidth >= padding;
  const fitsBottom =
    nodeTop + scaledPrimaryHeight + scaledGap + scaledGalleryHeight <=
    layout.visibleHeight - padding;
  const fitsTop = nodeTop - scaledGap - scaledGalleryHeight >= padding;
  let galleryLeft = primaryWidth + IMAGE_RESULTS_GALLERY_GAP;
  let galleryTop = 0;
  let placement = "right";

  if (!fitsRight && fitsLeft) {
    galleryLeft = -(galleryWidth + IMAGE_RESULTS_GALLERY_GAP);
    placement = "left";
  } else if (!fitsRight && !fitsLeft && fitsBottom) {
    galleryLeft = inlineLeft;
    galleryTop = primaryHeight + IMAGE_RESULTS_GALLERY_GAP;
    placement = "bottom";
  } else if (!fitsRight && !fitsLeft && fitsTop) {
    galleryLeft = inlineLeft;
    galleryTop = -(galleryHeight + IMAGE_RESULTS_GALLERY_GAP);
    placement = "top";
  } else if (!fitsRight) {
    const rightSpace = layout.visibleWidth - (nodeLeft + scaledPrimaryWidth);
    const leftSpace = nodeLeft;
    if (leftSpace > rightSpace) {
      galleryLeft = -(galleryWidth + IMAGE_RESULTS_GALLERY_GAP);
      placement = "left";
    }
  }

  return {
    primaryWidth,
    galleryWidth,
    galleryHeight,
    galleryLeft: Math.round(galleryLeft),
    galleryTop: Math.round(galleryTop),
    galleryColumns: sideColumns,
    sideCount,
    placement,
  };
};

const imageResultsExpansionStyleFromLayout = (
  layout: ImageResultsExpansionLayout | null,
): CSSProperties => {
  if (!layout) return {};
  return {
    "--aigc-image-primary-width": `${layout.primaryWidth}px`,
    "--aigc-image-gallery-width": `${layout.galleryWidth}px`,
    "--aigc-image-gallery-height": `${layout.galleryHeight}px`,
    "--aigc-image-gallery-left": `${layout.galleryLeft}px`,
    "--aigc-image-gallery-top": `${layout.galleryTop}px`,
    "--aigc-image-gallery-columns": layout.galleryColumns,
    "--aigc-image-gallery-count": layout.sideCount,
    "--aigc-image-gallery-placement": layout.placement,
  } as CSSProperties;
};

const imageResultsExpansionStyle = (
  node: AigcCanvasNode,
  layout: Parameters<typeof imageResultsExpansionLayout>[1],
): CSSProperties => {
  if (!isExpandedImageResultsNode(node)) return {};
  return imageResultsExpansionStyleFromLayout(
    savedImageResultsExpansionLayout(node) ??
      imageResultsExpansionLayout(node, layout),
  );
};

const imageResultsExpansionData = (
  node: AigcCanvasNode,
  layout: Parameters<typeof imageResultsExpansionLayout>[1],
) => {
  const expansionLayout = imageResultsExpansionLayout(node, layout);
  if (!expansionLayout) return {};
  return {
    imageResultsPrimaryWidth: expansionLayout.primaryWidth,
    imageResultsGalleryWidth: expansionLayout.galleryWidth,
    imageResultsGalleryHeight: expansionLayout.galleryHeight,
    imageResultsGalleryLeft: expansionLayout.galleryLeft,
    imageResultsGalleryTop: expansionLayout.galleryTop,
    imageResultsGalleryColumns: expansionLayout.galleryColumns,
    imageResultsGalleryPlacement: expansionLayout.placement,
  };
};

function AigcAssetOutput({ asset }: { asset: AigcAsset }) {
  const previewSource =
    asset.kind === "image" ? assetPreviewSource(asset) : undefined;
  const label = asset.name || asset.path || asset.id;

  if (previewSource) {
    return (
      <figure className={styles.outputPreview}>
        <AuthenticatedAssetImage src={previewSource} alt={label} />
        <figcaption className={styles.outputCaption}>{label}</figcaption>
      </figure>
    );
  }

  return <div className={styles.outputPath}>{asset.url ?? asset.path}</div>;
}

export default function AigcStudioPage() {
  const { t } = useTranslation();
  const guide = useAigcGuideTask(window.location.search);
  const returnToGuidedConversation = useGuidedTaskReturn(guide.task, (path) =>
    window.location.assign(path),
  );
  const canvasSurfaceRef = useRef<HTMLDivElement | null>(null);
  const canvasImageInputRef = useRef<HTMLInputElement | null>(null);
  const canvasVideoInputRef = useRef<HTMLInputElement | null>(null);
  const canvasAudioInputRef = useRef<HTMLInputElement | null>(null);
  const pendingCanvasUploadPositionRef = useRef<CanvasPoint | null>(null);
  const [viewportScale, setViewportScale] = useState(1);
  const {
    autoSaveTimerRef,
    savedCanvasSignatureRef,
    capabilities,
    capabilityDefaults,
    canvases,
    setCanvases,
    activeCanvas,
    setActiveCanvas,
    jobs,
    setJobs,
    autoSaveStatus,
    setAutoSaveStatus,
    loading,
    saving,
    persistCanvas,
    activateCanvasById,
  } = useCanvasPersistence({
    t,
    onViewportScaleChange: setViewportScale,
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(
    "image-1",
  );
  const [editingTextNodeId, setEditingTextNodeId] = useState<string | null>(
    null,
  );
  const {
    addMenuOpen,
    setAddMenuOpen,
    addMenuAnchor,
    setAddMenuAnchor,
    contextMenu,
    setContextMenu,
    canvasContextMenu,
    setCanvasContextMenu,
    quickTemplateMenu,
    setQuickTemplateMenu,
    portMenu,
    setPortMenu,
    closeCanvasMenus,
    openAddMenu,
    openCanvasContextMenu,
    openNodeContextMenu,
    openPortMenu,
  } = useCanvasFloatingMenus();
  const [draggingNode, setDraggingNode] = useState<CanvasNodeDragState | null>(
    null,
  );
  const [portDrag, setPortDrag] = useState<CanvasPortDragState | null>(null);
  const [handleCenters, setHandleCenters] = useState<CanvasHandleCenters>({});
  const suppressNextPortClickRef = useRef(false);
  const [panningCanvas, setPanningCanvas] = useState<CanvasPanState | null>(
    null,
  );
  const [spacePressed, setSpacePressed] = useState(false);
  const [textModelMenuNodeId, setTextModelMenuNodeId] = useState<string | null>(
    null,
  );
  const [imageComposerMenu, setImageComposerMenu] = useState<{
    nodeId: string;
    menu: ImageComposerMenu;
  } | null>(null);
  const [annotationEditorNodeId, setAnnotationEditorNodeId] = useState<
    string | null
  >(null);
  const [videoComposerMenu, setVideoComposerMenu] = useState<{
    nodeId: string;
    menu: VideoComposerMenu;
  } | null>(null);
  const [railPanel, setRailPanel] = useState<RailPanel>(null);
  const [minimapOpen, setMinimapOpen] = useState(false);
  const [canvasSurfaceSize, setCanvasSurfaceSize] = useState({
    visibleWidth: 1200,
    visibleHeight: 760,
  });
  const [clipboardNode, setClipboardNode] = useState<AigcCanvasNode | null>(
    null,
  );
  const [deletedNodeSnapshot, setDeletedNodeSnapshot] =
    useState<DeletedNodeSnapshot | null>(null);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [runningNodeKeys, setRunningNodeKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const [exportingLongImageNodeId, setExportingLongImageNodeId] = useState<
    string | null
  >(null);
  const runningNodeKeysRef = useRef<Set<string>>(new Set());
  const activeCanvasRef = useRef<AigcCanvas | null>(null);
  const imageProgressSimulation = useGenerationProgressSimulation();
  const videoProgressSimulation = useGenerationProgressSimulation();

  useEffect(() => {
    activeCanvasRef.current = activeCanvas;
  }, [activeCanvas]);

  useEffect(() => {
    const binding = guide.task?.binding;
    if (!binding) return;
    const targetNodeId = guide.guide?.current_step?.node_id ?? binding.node_id;
    if (activeCanvas?.id === binding.canvas_id) {
      if (targetNodeId && selectedNodeId !== targetNodeId) {
        setSelectedNodeId(targetNodeId);
      }
      return;
    }
    let active = true;
    void activateCanvasById(binding.canvas_id)
      .then(() => {
        if (active && targetNodeId) setSelectedNodeId(targetNodeId);
      })
      .catch(() => {
        if (active) {
          antdMessage.error(
            "无法打开当前任务绑定的画布，请从原会话重新进入任务",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [
    activeCanvas?.id,
    activateCanvasById,
    guide.task?.binding,
    guide.guide?.current_step?.node_id,
    selectedNodeId,
  ]);

  useEffect(() => {
    const updateSurfaceSize = () => {
      const surfaceRect = canvasSurfaceRef.current?.getBoundingClientRect();
      if (!surfaceRect) return;
      setCanvasSurfaceSize((current) => {
        const visibleWidth = Math.round(surfaceRect.width);
        const visibleHeight = Math.round(surfaceRect.height);
        if (
          current.visibleWidth === visibleWidth &&
          current.visibleHeight === visibleHeight
        ) {
          return current;
        }
        return { visibleWidth, visibleHeight };
      });
    };
    updateSurfaceSize();
    const surface = canvasSurfaceRef.current;
    const observer =
      surface && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(updateSurfaceSize)
        : null;
    if (surface && observer) {
      observer.observe(surface);
    }
    window.addEventListener("resize", updateSurfaceSize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateSurfaceSize);
    };
  }, []);

  const selectedNode = activeCanvas?.nodes.find(
    (node) => node.id === selectedNodeId,
  );
  const capabilityForCanvasNode = (node: AigcCanvasNode) => {
    const boundCapability = String(node.data.modelCapability ?? "").trim();
    return boundCapability || capabilityForNode(node.type);
  };
  const annotationEditorNode = annotationEditorNodeId
    ? activeCanvas?.nodes.find((node) => node.id === annotationEditorNodeId)
    : undefined;
  const annotationEditorSourcePreviewUrl = annotationEditorNode
    ? imageAnnotationSourcePreviewUrl(annotationEditorNode)
    : "";
  const selectedCapability = selectedNode
    ? capabilityForCanvasNode(selectedNode)
    : "text_to_image";
  const selectedNodeUsesModel = selectedNode
    ? !isWorkflowOnlyNodeType(selectedNode.type)
    : false;
  const selectedNodeModel =
    selectedNodeUsesModel && selectedNode
      ? modelForNode(
          capabilities,
          selectedNode,
          selectedCapability,
          effectiveDefaultForCapability(capabilityDefaults, selectedCapability),
        )
      : null;
  const selectedNodeModelState =
    selectedNodeUsesModel && selectedNode
      ? modelSelectionState(
          capabilities,
          selectedNode,
          selectedCapability,
          effectiveDefaultForCapability(capabilityDefaults, selectedCapability),
        )
      : null;
  const selectedNodeModelOptions =
    selectedNodeUsesModel && selectedNode
      ? modelOptionsForNode(capabilities, selectedNode, selectedCapability)
      : [];
  const selectedNodeModelKey = modelKey(selectedNodeModel);
  const runningNodeKey = (canvasId: string, nodeId: string) =>
    `${canvasId}:${nodeId}`;
  const isNodeRunning = (nodeId?: string | null) =>
    Boolean(
      activeCanvas?.id &&
        nodeId &&
        runningNodeKeys.has(runningNodeKey(activeCanvas.id, nodeId)),
    );
  const selectedNodeRunning = selectedNode
    ? isNodeRunning(selectedNode.id)
    : false;
  const contextMenuNode = contextMenu
    ? activeCanvas?.nodes.find((node) => node.id === contextMenu.nodeId)
    : undefined;
  const portMenuNode = portMenu
    ? activeCanvas?.nodes.find((node) => node.id === portMenu.nodeId)
    : undefined;
  const canvasBounds = useMemo(() => {
    const nodes = activeCanvas?.nodes ?? [];
    if (!nodes.length) {
      return { minX: 0, minY: 0, width: 1, height: 1 };
    }
    const minX = Math.min(...nodes.map((node) => node.position.x));
    const minY = Math.min(...nodes.map((node) => node.position.y));
    const maxX = Math.max(
      ...nodes.map((node) => node.position.x + nodeVisualWidth(node)),
    );
    const maxY = Math.max(
      ...nodes.map((node) => node.position.y + nodeVisualHeight(node)),
    );
    return {
      minX,
      minY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY),
    };
  }, [activeCanvas]);
  const historyRecords = useMemo(() => {
    const records = [
      ...jobs.flatMap((job) =>
        job.outputs.map((asset, index) => ({
          id: `${job.id}-${index}`,
          title:
            asset.name || t("aigcStudio.history.generatedAsset", "生成结果"),
          kind: translatedCapability(t, job.capability),
          jobStatus: job.status,
        })),
      ),
      ...(activeCanvas?.nodes ?? []).flatMap((node) =>
        nodeOutputs(node).map((asset, index) => ({
          id: `${node.id}-${index}`,
          title:
            asset.name || t("aigcStudio.history.generatedAsset", "生成结果"),
          kind: translatedNodeType(t, node.type),
          jobStatus: String(node.data.job_status ?? "succeeded"),
        })),
      ),
    ];
    return Array.from(
      new Map(records.map((record) => [record.id, record])).values(),
    );
  }, [activeCanvas?.nodes, jobs, t]);
  const assetRecords = useMemo(
    () =>
      (activeCanvas?.nodes ?? [])
        .filter((node) => node.data.savedToAssets === true)
        .map((node) =>
          canvasAssetFromNode(
            t,
            node,
            t("aigcStudio.assets.kind.material", "素材"),
            `asset-${activeCanvas?.id}-${node.id}`,
          ),
        ),
    [activeCanvas?.id, activeCanvas?.nodes, t],
  );
  const subjectRecords = useMemo(
    () =>
      (activeCanvas?.nodes ?? [])
        .filter((node) => node.data.savedToSubjects === true)
        .map((node) =>
          canvasAssetFromNode(
            t,
            node,
            t("aigcStudio.assets.kind.subject", "主体"),
            `subject-${activeCanvas?.id}-${node.id}`,
          ),
        ),
    [activeCanvas?.id, activeCanvas?.nodes, t],
  );

  useEffect(() => {
    if (editingTextNodeId && selectedNodeId !== editingTextNodeId) {
      setEditingTextNodeId(null);
    }
  }, [editingTextNodeId, selectedNodeId]);

  useEffect(() => {
    if (!annotationEditorNodeId) return;
    const stillExists = activeCanvas?.nodes.some(
      (node) => node.id === annotationEditorNodeId,
    );
    if (!stillExists) {
      setAnnotationEditorNodeId(null);
    }
  }, [activeCanvas?.nodes, annotationEditorNodeId]);

  useLayoutEffect(() => {
    const surface = canvasSurfaceRef.current;
    if (!surface) {
      setHandleCenters((current) =>
        Object.keys(current).length === 0 ? current : {},
      );
      return;
    }

    const surfaceRect = surface.getBoundingClientRect();
    const nextCenters: CanvasHandleCenters = {};
    surface
      .querySelectorAll<HTMLButtonElement>("[data-aigc-node-handle='true']")
      .forEach((element) => {
        const nodeId = element.dataset.aigcNodeId;
        const side = element.dataset.aigcHandleSide;
        if (!nodeId || (side !== "left" && side !== "right")) return;
        const rect = element.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        nextCenters[canvasHandleCenterKey(nodeId, side)] = {
          x: rect.left - surfaceRect.left + rect.width / 2,
          y: rect.top - surfaceRect.top + rect.height / 2,
        };
      });

    setHandleCenters((current) =>
      sameHandleCenters(current, nextCenters) ? current : nextCenters,
    );
  });

  const edgeLines = useMemo(
    () => buildCanvasEdgeLines(activeCanvas, viewportScale, handleCenters),
    [activeCanvas, viewportScale, handleCenters],
  );
  const visibleEdgeLines = useMemo(
    () =>
      portDrag
        ? [
            ...edgeLines,
            {
              id: `draft-${portDrag.nodeId}-${portDrag.side}`,
              path: buildSurfaceEdgePath(
                { x: portDrag.startX, y: portDrag.startY },
                { x: portDrag.currentX, y: portDrag.currentY },
              ),
            },
          ]
        : edgeLines,
    [edgeLines, portDrag],
  );

  const handleCreateCanvas = async () => {
    const result = await createCanvasProject({
      t,
      activeCanvas,
      savedCanvasSignature: savedCanvasSignatureRef.current,
      persistCanvas,
    });
    savedCanvasSignatureRef.current = result.signature;
    setCanvases((prev) => [result.canvas, ...prev]);
    setActiveCanvas(result.canvas);
    setViewportScale(result.canvas.viewport.zoom || 1);
    setSelectedNodeId(null);
    setJobs([]);
    setProjectMenuOpen(false);
    setRailPanel(null);
    setMinimapOpen(false);
    setAutoSaveStatus("saved");
  };

  const handleSave = async () => {
    if (!activeCanvas) return;
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }
    await persistCanvas(activeCanvas);
  };

  const handleSelectCanvas = async (canvas: AigcCanvas) => {
    if (activeCanvas?.id === canvas.id) {
      setProjectMenuOpen(false);
      return;
    }
    const result = await selectCanvasProject({
      activeCanvas,
      targetCanvas: canvas,
      savedCanvasSignature: savedCanvasSignatureRef.current,
      persistCanvas,
    });
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }
    savedCanvasSignatureRef.current = result.signature;
    setActiveCanvas(result.canvas);
    setViewportScale(result.canvas.viewport.zoom || 1);
    setSelectedNodeId(result.canvas.nodes[0]?.id ?? null);
    setProjectMenuOpen(false);
    setRailPanel(null);
    setMinimapOpen(false);
    setAutoSaveStatus("saved");
    setJobs(result.jobs);
  };

  const handleDeleteCanvas = async (
    canvas: AigcCanvas,
    event: ReactMouseEvent<HTMLButtonElement>,
  ) => {
    event.stopPropagation();
    const confirmed = window.confirm(
      t(
        "aigcStudio.projects.deleteConfirm",
        "确定删除「{{name}}」吗？该项目的画布和任务记录会一起删除。",
        { name: canvas.name },
      ),
    );
    if (!confirmed) return;

    if (canvas.id === activeCanvas?.id && autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
      autoSaveTimerRef.current = null;
    }

    try {
      const result = await deleteCanvasProject({
        canvas,
        activeCanvas,
        canvases,
      });
      setCanvases(result.remainingCanvases);

      if (activeCanvas?.id === canvas.id) {
        setActiveCanvas(result.nextCanvas);
        setSelectedNodeId(result.nextCanvas?.nodes[0]?.id ?? null);
        setJobs([]);
        savedCanvasSignatureRef.current = result.nextSignature;
        setAutoSaveStatus("saved");
        if (result.nextCanvas) {
          void aigcStudioApi
            .listJobs(result.nextCanvas.id)
            .then((result) => setJobs(result.jobs));
        }
      }
    } catch (error) {
      console.error("Failed to delete AIGC canvas", error);
      setAutoSaveStatus("error");
      return;
    }
  };

  const selectNodeModel = (
    node: AigcCanvasNode,
    model: NonNullable<typeof selectedNodeModel>,
    extraData: Record<string, unknown> = {},
  ) => {
    updateNodeData(node.id, {
      modelLabel: model.model_name ?? model.model_id,
      providerId: model.provider_id,
      providerName: model.provider_name,
      modelId: model.model_id,
      modelCapability: model.capability,
      ...extraData,
    });
  };

  const modelOptionsForCanvasNode = (node: AigcCanvasNode) =>
    isWorkflowOnlyNodeType(node.type)
      ? []
      : modelOptionsForNode(capabilities, node, capabilityForCanvasNode(node));

  const currentModelForCanvasNode = (node: AigcCanvasNode) =>
    isWorkflowOnlyNodeType(node.type)
      ? null
      : modelForNode(
          capabilities,
          node,
          capabilityForCanvasNode(node),
          effectiveDefaultForCapability(
            capabilityDefaults,
            capabilityForCanvasNode(node),
          ),
        );

  const currentModelKeyForCanvasNode = (node: AigcCanvasNode) =>
    modelKey(currentModelForCanvasNode(node));

  const setNodeRunning = (
    canvasId: string,
    nodeId: string,
    running: boolean,
  ) => {
    const key = runningNodeKey(canvasId, nodeId);
    const next = new Set(runningNodeKeysRef.current);
    if (running) {
      next.add(key);
    } else {
      next.delete(key);
    }
    runningNodeKeysRef.current = next;
    setRunningNodeKeys(next);
  };

  const canvasWithNodeSnapshot = (
    canvas: AigcCanvas,
    nodeSnapshot: AigcCanvasNode,
  ): AigcCanvas => ({
    ...canvas,
    nodes: canvas.nodes.map((node) =>
      node.id === nodeSnapshot.id
        ? {
            ...node,
            ...nodeSnapshot,
            data: {
              ...node.data,
              ...nodeSnapshot.data,
            },
          }
        : node,
    ),
  });

  const runNode = async (
    nodeToRun: AigcCanvasNode | null,
    canvasOverride?: AigcCanvas,
  ) => {
    const canvasForRunSource = canvasOverride ?? activeCanvas;
    if (!canvasForRunSource || !nodeToRun) return;
    const nodeCapability = capabilityForCanvasNode(nodeToRun);
    const selection = modelSelectionState(
      capabilities,
      nodeToRun,
      nodeCapability,
      effectiveDefaultForCapability(capabilityDefaults, nodeCapability),
    );
    if (selection.invalidSavedModel && !selection.fallback) {
      antdMessage.error(
        t(
          "aigcStudio.noFallbackModel",
          "该模型已不可用，且当前没有可切换的默认模型。",
        ),
      );
      return;
    }
    if (selection.invalidSavedModel && selection.fallback) {
      const confirmed = await new Promise<boolean>((resolve) => {
        Modal.confirm({
          title: t("aigcStudio.modelUnavailable", "该模型已不可用"),
          content: t(
            "aigcStudio.switchToDefaultModel",
            "是否切换到当前默认模型 {{model}} 后继续？",
            { model: selection.fallback?.model_name },
          ),
          okText: t("aigcStudio.switchAndContinue", "切换并继续"),
          cancelText: t("common.cancel", "取消"),
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!confirmed) return;
      const switchedNode = {
        ...nodeToRun,
        data: {
          ...nodeToRun.data,
          modelLabel: selection.fallback.model_name,
          providerId: selection.fallback.provider_id,
          providerName: selection.fallback.provider_name,
          modelId: selection.fallback.model_id,
          modelCapability: selection.fallback.capability,
        },
      };
      updateNodeData(nodeToRun.id, switchedNode.data);
      await runNode(switchedNode, canvasOverride);
      return;
    }
    const nodeRunKey = runningNodeKey(canvasForRunSource.id, nodeToRun.id);
    if (runningNodeKeysRef.current.has(nodeRunKey)) return;
    const isFeedbackNode = [
      "image_generate",
      "prompt",
      "video_generate",
      "audio_generate",
      "script_generate",
    ].includes(nodeToRun.type);
    const latestCanvasForNodeRun = () => {
      const activeSnapshot = activeCanvasRef.current;
      if (
        activeSnapshot?.id === canvasForRunSource.id &&
        activeSnapshot.nodes.some((node) => node.id === nodeToRun.id)
      ) {
        return activeSnapshot;
      }
      return canvasForRunSource;
    };
    const patchNodeData = (data: Record<string, unknown>) => {
      const latestCanvas = latestCanvasForNodeRun();
      commitCanvas(
        canvasWithNodeSnapshot(latestCanvas, {
          ...nodeToRun,
          data: {
            ...nodeToRun.data,
            ...data,
          },
        }),
      );
    };
    const failurePatch = (message: string): Record<string, unknown> => {
      const base = {
        job_status: "failed",
        job_error: message,
      };
      if (nodeToRun.type === "image_generate") {
        return { ...base, imageState: "failed", imageProgress: null };
      }
      if (nodeToRun.type === "prompt") {
        return { ...base, textState: "failed" };
      }
      if (nodeToRun.type === "video_generate") {
        return { ...base, videoState: "failed", videoProgress: null };
      }
      if (nodeToRun.type === "audio_generate") {
        return { ...base, audioState: "failed", audioProgress: null };
      }
      if (nodeToRun.type === "script_generate") {
        return {
          ...base,
          scriptMode: "script_ready",
          scriptProgress: null,
          scriptParseStatus: "failed",
          scriptParseError: message,
        };
      }
      return base;
    };
    const runModel = modelForNode(
      capabilities,
      nodeToRun,
      nodeCapability,
      effectiveDefaultForCapability(capabilityDefaults, nodeCapability),
    );
    if (!runModel) {
      const missingModelMessage =
        nodeToRun.type === "image_generate"
          ? t(
              "aigcStudio.imageNode.missingModel",
              "当前图片节点没有可用模型，请先选择模型后再生成。",
            )
          : nodeToRun.type === "prompt"
          ? t(
              "aigcStudio.textNode.missingModel",
              "当前文本节点没有可用模型，请先选择模型后再生成。",
            )
          : nodeToRun.type === "video_generate"
          ? t(
              "aigcStudio.videoNode.missingModel",
              "当前视频节点没有可用模型，请先选择模型后再生成。",
            )
          : nodeToRun.type === "audio_generate"
          ? t(
              "aigcStudio.audioNode.missingModel",
              "当前音频节点没有可用模型，请先选择模型后再生成。",
            )
          : nodeToRun.type === "script_generate"
          ? t(
              "aigcStudio.scriptNode.missingModel",
              "当前脚本节点没有可用模型，请先选择模型后再生成。",
            )
          : t(
              "aigcStudio.node.missingModel",
              "当前节点没有可用模型，请先选择模型后再生成。",
            );
      patchNodeData(failurePatch(missingModelMessage));
      return;
    }
    const latestCanvasForRun = latestCanvasForNodeRun();
    const canvasForRun = canvasWithNodeSnapshot(latestCanvasForRun, nodeToRun);
    const jobRequest = buildRunNodeJobRequest({
      canvas: canvasForRun,
      selectedNode: nodeToRun,
      selectedCapability: nodeCapability,
      selectedModel: runModel,
    });
    if (!jobRequest.ok) {
      updateNodeData(nodeToRun.id, {
        slashReferenceError: t(
          "aigcStudio.imageNode.slashReferenceRequired",
          "请先上传或连接参考图，再运行这个快捷指令。",
        ),
      });
      return;
    }
    const runningPatch =
      nodeToRun.type === "image_generate"
        ? {
            slashReferenceError: null,
            imageState: "generating",
            imageProgress: 2,
            job_status: "running",
            job_error: null,
            outputs: [],
          }
        : nodeToRun.type === "prompt"
        ? {
            textState: "generating",
            job_status: "running",
            job_error: null,
            outputs: [],
            showTryOptions: false,
          }
        : nodeToRun.type === "video_generate"
        ? {
            videoState: "generating",
            videoProgress: 1,
            job_status: "running",
            job_error: null,
            outputs: [],
          }
        : nodeToRun.type === "audio_generate"
        ? {
            audioState: "generating",
            audioProgress: 1,
            job_status: "running",
            job_error: null,
            outputs: [],
          }
        : nodeToRun.type === "script_generate"
        ? {
            scriptMode: "generating_script",
            scriptProgress: 4,
            scriptParseStatus: null,
            scriptParseError: null,
            job_status: "running",
            job_error: null,
            outputs: [],
          }
        : null;
    setNodeRunning(canvasForRunSource.id, nodeToRun.id, true);
    try {
      const runNodeSnapshot = runningPatch
        ? {
            ...nodeToRun,
            data: {
              ...nodeToRun.data,
              ...runningPatch,
            },
          }
        : null;
      const canvasToPersist = runNodeSnapshot
        ? canvasWithNodeSnapshot(canvasForRun, runNodeSnapshot)
        : canvasForRun;
      if (runNodeSnapshot) {
        commitCanvas(canvasToPersist);
      } else if (nodeToRun.data.slashReferenceError) {
        updateNodeData(nodeToRun.id, { slashReferenceError: null });
      }
      if (isFeedbackNode) {
        if (autoSaveTimerRef.current) {
          clearTimeout(autoSaveTimerRef.current);
          autoSaveTimerRef.current = null;
        }
        await persistCanvas(canvasToPersist);
      }
      if (isFeedbackNode) {
        await waitForCanvasFeedbackFrame();
      }
      if (nodeToRun.type === "image_generate") {
        imageProgressSimulation.startProgressSimulation({
          nodeId: nodeToRun.id,
          model: runModel,
          parameters: jobRequest.request.parameters,
        });
      } else if (nodeToRun.type === "video_generate") {
        videoProgressSimulation.startProgressSimulation({
          nodeId: nodeToRun.id,
          model: runModel,
          parameters: jobRequest.request.parameters,
        });
      }
      const job = await aigcStudioApi.submitJob(jobRequest.request);
      setJobs((prev) => prependCanvasJob(prev, job));
      const finished = await aigcStudioApi.runJob(job.id);
      if (nodeToRun.type === "image_generate") {
        imageProgressSimulation.clearProgressSimulation(nodeToRun.id);
      } else if (nodeToRun.type === "video_generate") {
        videoProgressSimulation.clearProgressSimulation(nodeToRun.id);
      }
      setJobs((prev) => replaceCanvasJob(prev, finished));
      setActiveCanvas((canvas) => {
        if (!canvas) return canvas;
        const updated = applyFinishedJobToCanvas({
          canvas,
          nodeId: nodeToRun.id,
          job: finished,
        });
        activeCanvasRef.current = updated;
        setCanvases((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
        return updated;
      });
      if (guide.taskId) await guide.refresh();
    } catch (error) {
      console.error("Failed to run AIGC node", error);
      if (isFeedbackNode) {
        imageProgressSimulation.clearProgressSimulation(nodeToRun.id);
        videoProgressSimulation.clearProgressSimulation(nodeToRun.id);
        patchNodeData(
          failurePatch(
            error instanceof Error
              ? error.message
              : t("aigcStudio.node.failedHint", "请调整输入后重试。"),
          ),
        );
      }
    } finally {
      if (nodeToRun.type === "image_generate") {
        imageProgressSimulation.clearProgressSimulation(nodeToRun.id);
      } else if (nodeToRun.type === "video_generate") {
        videoProgressSimulation.clearProgressSimulation(nodeToRun.id);
      }
      setNodeRunning(canvasForRunSource.id, nodeToRun.id, false);
    }
  };

  const handleRunNode = async (
    _event?: unknown,
    nodeSnapshot?: AigcCanvasNode,
  ) => {
    await runNode(nodeSnapshot ?? selectedNode ?? null);
  };

  const handleRunImageComposerNode = async (nodeToRun: AigcCanvasNode) => {
    await runNode(nodeToRun);
  };

  const handleExportLongImage = async (nodeToExport: AigcCanvasNode) => {
    const canvasSnapshot =
      activeCanvasRef.current?.id === activeCanvas?.id
        ? activeCanvasRef.current
        : activeCanvas;
    if (!canvasSnapshot) return;
    const sliceHeight = Number(nodeToExport.data.sliceHeight ?? 1400);
    const width = Number(nodeToExport.data.exportWidth ?? 750);
    setExportingLongImageNodeId(nodeToExport.id);
    updateNodeData(nodeToExport.id, {
      job_status: "running",
      job_error: null,
      longImageState: "exporting",
    });
    try {
      const result = await aigcStudioApi.exportLongImage({
        canvas_id: canvasSnapshot.id,
        node_id: nodeToExport.id,
        width: Number.isFinite(width) ? width : 750,
        slice_height: Number.isFinite(sliceHeight) ? sliceHeight : 1400,
      });
      setActiveCanvas((canvas) => {
        if (!canvas) return canvas;
        const updated = {
          ...canvas,
          nodes: canvas.nodes.map((node) =>
            node.id === nodeToExport.id
              ? {
                  ...node,
                  data: {
                    ...node.data,
                    job_status: "succeeded",
                    longImageState: "exported",
                    longImageExportedAt: new Date().toISOString(),
                    longImageWidth: result.width,
                    longImageHeight: result.height,
                    longImageSliceHeight: result.slice_height,
                    longImageSectionCount: result.section_count,
                    outputs: [result.full_asset, ...result.slice_assets],
                  },
                }
              : node,
          ),
        };
        activeCanvasRef.current = updated;
        setCanvases((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
        return updated;
      });
      if (guide.taskId) await guide.refresh();
    } catch (error) {
      console.error("Failed to export long image", error);
      updateNodeData(nodeToExport.id, {
        job_status: "failed",
        longImageState: "failed",
        job_error:
          error instanceof Error
            ? error.message
            : t("aigcStudio.longImageExport.failed", "长图导出失败。"),
      });
    } finally {
      setExportingLongImageNodeId(null);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    const cancelled = await aigcStudioApi.cancelJob(jobId);
    setJobs((prev) => replaceCanvasJob(prev, cancelled));
  };

  const handleRetryJob = async (jobId: string) => {
    const retried = await aigcStudioApi.retryJob(jobId);
    setJobs((prev) => prependCanvasJob(prev, retried));
    if (guide.taskId) await guide.refresh();
  };

  const updateCanvasName = (name: string) => {
    setActiveCanvas((canvas) => (canvas ? { ...canvas, name } : canvas));
    setCanvases((prev) =>
      prev.map((canvas) =>
        canvas.id === activeCanvas?.id ? { ...canvas, name } : canvas,
      ),
    );
  };

  const closeExternalFloatingMenus = () => {
    setTextModelMenuNodeId(null);
    setImageComposerMenu(null);
    setVideoComposerMenu(null);
    setProjectMenuOpen(false);
  };

  const closeFloatingMenus = () => {
    closeCanvasMenus();
    closeExternalFloatingMenus();
  };

  const surfacePointFromClient = (
    clientX: number,
    clientY: number,
  ): CanvasPoint => {
    const surfaceRect = canvasSurfaceRef.current?.getBoundingClientRect();
    return {
      x: clientX - (surfaceRect?.left ?? 0),
      y: clientY - (surfaceRect?.top ?? 0),
    };
  };

  const surfacePointFromElementCenter = (
    element: HTMLElement,
  ): CanvasPoint | null => {
    const surfaceRect = canvasSurfaceRef.current?.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    if (!surfaceRect || elementRect.width <= 0 || elementRect.height <= 0) {
      return null;
    }
    return {
      x: elementRect.left - surfaceRect.left + elementRect.width / 2,
      y: elementRect.top - surfaceRect.top + elementRect.height / 2,
    };
  };

  const nodePortSurfacePoint = (
    node: AigcCanvasNode,
    side: PortSide,
  ): CanvasPoint =>
    handleCenters[canvasHandleCenterKey(node.id, side)] ??
    nodeHandleCenterSurfacePoint({
      node,
      side,
      viewport: activeCanvas?.viewport ?? {
        x: 0,
        y: 0,
        zoom: viewportScale,
      },
      scale: viewportScale,
    });

  const nodeIdFromClientPoint = (clientX: number, clientY: number) => {
    const element = document.elementFromPoint?.(
      clientX,
      clientY,
    ) as HTMLElement | null;
    return (
      element
        ?.closest<HTMLElement>("[data-aigc-node-id]")
        ?.getAttribute("data-aigc-node-id") ?? null
    );
  };

  const openPortMenuAtSurfacePoint = (
    node: AigcCanvasNode,
    side: PortSide,
    point: CanvasPoint,
  ) => {
    setSelectedNodeId(node.id);
    openPortMenu({
      nodeId: node.id,
      side,
      x: side === "left" ? Math.max(8, point.x - 248) : point.x + 14,
      y: point.y - 12,
    });
    closeExternalFloatingMenus();
  };

  const canvasPointFromClient = (
    clientX: number,
    clientY: number,
  ): CanvasPoint => {
    const point = surfacePointFromClient(clientX, clientY);
    return surfacePointToCanvasPoint({
      point,
      viewport: activeCanvas?.viewport ?? { x: 0, y: 0, zoom: viewportScale },
      scale: viewportScale,
      min: Number.NEGATIVE_INFINITY,
    });
  };

  const commitViewport = (viewport: AigcCanvas["viewport"]) => {
    setActiveCanvas((canvas) => {
      if (!canvas) return canvas;
      const updated = { ...canvas, viewport };
      setCanvases((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      return updated;
    });
  };

  const offsetViewport = (deltaX: number, deltaY: number) => {
    setActiveCanvas((canvas) => {
      if (!canvas) return canvas;
      const updated = {
        ...canvas,
        viewport: offsetCanvasViewport({
          viewport: canvas.viewport,
          deltaX,
          deltaY,
          fallbackScale: viewportScale,
        }),
      };
      setCanvases((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      return updated;
    });
  };

  const handleAddNodeAt = (type: string, position?: CanvasPoint) => {
    if (!activeCanvas) return;
    const node = createNodeForType(t, type, activeCanvas.nodes.length);
    const fallbackPosition = defaultNodePositionInViewport({
      viewport: activeCanvas.viewport,
      scale: viewportScale,
      visibleWidth: canvasSurfaceSize.visibleWidth,
      visibleHeight: canvasSurfaceSize.visibleHeight,
      nodeWidth: nodeVisualWidth(node),
      nodeHeight: nodeVisualHeight(node),
      nodeCount: activeCanvas.nodes.length,
    });
    const nextNode = { ...node, position: position ?? fallbackPosition };
    const updated = {
      ...activeCanvas,
      nodes: [...activeCanvas.nodes, nextNode],
    };
    setActiveCanvas(updated);
    setCanvases((prev) =>
      prev.map((canvas) => (canvas.id === updated.id ? updated : canvas)),
    );
    setSelectedNodeId(nextNode.id);
    setRailPanel(null);
    closeFloatingMenus();
  };

  const handleAddNode = (type: string) => {
    handleAddNodeAt(type, addMenuAnchor?.position);
  };

  const handleCanvasFiles = async (
    files: FileList | File[] | null | undefined,
    position: CanvasPoint,
  ) => {
    if (!activeCanvas || !files) return;
    const pickedFiles = filterCanvasAssetFiles(files);
    const fileCount = Array.from(files).length;
    if (!pickedFiles.length) {
      if (fileCount > 0) {
        antdMessage.warning(
          t(
            "aigcStudio.upload.unsupported",
            "暂不支持这些文件，请上传图片、视频或音频素材。",
          ),
        );
      }
      return;
    }
    const toastKey = `aigc-canvas-upload-${Date.now()}-${pickedFiles.length}`;
    antdMessage.loading({
      content: t(
        "aigcStudio.upload.uploading",
        "正在上传 {{count}} 个素材...",
        {
          count: pickedFiles.length,
        },
      ),
      key: toastKey,
      duration: 0,
    });
    try {
      const uploadedAssets = await Promise.all(
        pickedFiles.map((file) => aigcStudioApi.uploadAsset(file)),
      );
      const nodes = buildUploadedAssetNodes({
        t,
        files: pickedFiles,
        assets: uploadedAssets,
        position,
        nodeCount: activeCanvas.nodes.length,
      });
      const updated = appendCanvasNodes(activeCanvas, nodes);
      commitCanvas(updated);
      setSelectedNodeId(nodes[nodes.length - 1]?.id ?? selectedNodeId);
      setRailPanel(null);
      closeFloatingMenus();
      antdMessage.success({
        content: t("aigcStudio.upload.success", "已上传 {{count}} 个素材", {
          count: pickedFiles.length,
        }),
        key: toastKey,
        duration: 2,
      });
    } catch (error) {
      console.error("Failed to upload AIGC canvas files", error);
      antdMessage.error({
        content: t(
          "aigcStudio.upload.failed",
          "素材上传失败，请检查文件后再试。",
        ),
        key: toastKey,
        duration: 3,
      });
    }
  };

  const handleCanvasFileInput = (event: ReactChangeEvent<HTMLInputElement>) => {
    const position =
      pendingCanvasUploadPositionRef.current ??
      canvasContextMenu?.position ??
      defaultAssetNodePosition(activeCanvas?.nodes.length ?? 0);
    pendingCanvasUploadPositionRef.current = null;
    void handleCanvasFiles(event.target.files, position);
    event.target.value = "";
  };

  const handleOpenCanvasUploadInput = (
    input: HTMLInputElement | null,
    position: CanvasPoint,
  ) => {
    if (!input) return;
    pendingCanvasUploadPositionRef.current = position;
    input.click();
  };

  const handleCanvasDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    void handleCanvasFiles(
      event.dataTransfer.files,
      canvasPointFromClient(event.clientX, event.clientY),
    );
  };

  const handleCanvasContextMenu = (event: ReactMouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const point = surfacePointFromClient(event.clientX, event.clientY);
    openCanvasContextMenu({
      ...point,
      position: canvasPointFromClient(event.clientX, event.clientY),
    });
    setSelectedNodeId(null);
    setRailPanel(null);
    closeExternalFloatingMenus();
  };

  const handleCanvasDoubleClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (
      target?.closest(
        "[data-aigc-node],button,input,textarea,select,label,[contenteditable='true']",
      )
    ) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const point = surfacePointFromClient(event.clientX, event.clientY);
    openAddMenu({
      ...point,
      position: canvasPointFromClient(event.clientX, event.clientY),
    });
    setSelectedNodeId(null);
    setRailPanel(null);
    closeExternalFloatingMenus();
  };

  const handleTemplateNode = (
    variant: TemplateVariant,
    anchorPosition?: CanvasPoint,
  ) => {
    if (!activeCanvas) return;
    const template = createTemplateParts(t, variant, activeCanvas.nodes.length);
    const nodes = repositionTemplateNodes(template.nodes, anchorPosition);
    const updated = appendTemplateParts({
      canvas: activeCanvas,
      nodes,
      edges: template.edges,
    });
    commitCanvas(updated);
    setSelectedNodeId(template.selectedNodeId);
    setRailPanel(null);
    closeFloatingMenus();
  };

  const handleNodeContextMenu = (
    event: ReactMouseEvent<HTMLDivElement>,
    nodeId: string,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const surfaceRect = canvasSurfaceRef.current?.getBoundingClientRect();
    setSelectedNodeId(nodeId);
    openNodeContextMenu({
      nodeId,
      x: event.clientX - (surfaceRect?.left ?? 0),
      y: event.clientY - (surfaceRect?.top ?? 0),
    });
    closeExternalFloatingMenus();
  };

  const handleOpenPortMenu = (
    event: ReactMouseEvent<HTMLButtonElement>,
    node: AigcCanvasNode,
    side: PortSide,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    if (suppressNextPortClickRef.current) {
      suppressNextPortClickRef.current = false;
      return;
    }
    const point = surfacePointFromClient(event.clientX, event.clientY);
    openPortMenuAtSurfacePoint(node, side, point);
  };

  const handlePortHandleMouseDown = (
    event: ReactMouseEvent<HTMLButtonElement>,
    node: AigcCanvasNode,
    side: PortSide,
  ) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const point =
      surfacePointFromElementCenter(event.currentTarget) ??
      nodePortSurfacePoint(node, side);
    suppressNextPortClickRef.current = true;
    setSelectedNodeId(node.id);
    setPortDrag({
      nodeId: node.id,
      side,
      startX: point.x,
      startY: point.y,
      currentX: point.x,
      currentY: point.y,
      hasMoved: false,
    });
    setContextMenu(null);
    setCanvasContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
    closeExternalFloatingMenus();
  };

  const handleNodeMouseDown = (
    event: ReactMouseEvent<HTMLDivElement>,
    node: AigcCanvasNode,
  ) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (
      target?.closest(
        "button,input,textarea,select,label,[contenteditable='true']",
      )
    ) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setSelectedNodeId(node.id);
    setDraggingNode({
      nodeId: node.id,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: node.position.x,
      startY: node.position.y,
    });
    setContextMenu(null);
    setCanvasContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
  };

  const handleCreatePortNode = (
    anchorNode: AigcCanvasNode,
    nodeType: string,
    side: PortSide,
  ) => {
    if (!activeCanvas) return;
    const node = createNodeForType(t, nodeType, activeCanvas.nodes.length);
    const createdNode: AigcCanvasNode = {
      ...node,
      position: portNodePosition({
        anchorNode,
        side,
        anchorWidth: nodeVisualWidth(anchorNode),
        createdWidth: nodeVisualWidth(node),
      }),
      data: {
        ...node.data,
        ...(side === "right"
          ? downstreamDataFromSource(t, anchorNode, nodeType)
          : nodeDataForContextTarget(t, nodeType)),
      },
    };
    const edge = createPortEdge({
      anchorNode,
      createdNode,
      side,
      role:
        side === "right"
          ? edgeRoleForSource(anchorNode)
          : edgeRoleForSource(createdNode),
    });
    commitCanvas(
      appendPortNode({ canvas: activeCanvas, node: createdNode, edge }),
    );
    setSelectedNodeId(createdNode.id);
    setPortMenu(null);
  };

  const handleDeleteNode = (nodeId?: string) => {
    if (!activeCanvas) return;
    const deletedNodeId =
      typeof nodeId === "string"
        ? nodeId
        : contextMenu?.nodeId ?? selectedNodeId;
    if (!deletedNodeId) return;
    const result = deleteCanvasNode({
      canvas: activeCanvas,
      nodeId: deletedNodeId,
      selectedNodeId,
    });
    if (!result) return;
    const removedOutgoingEdges = result.snapshot.edges.filter(
      (edge) => edge.source === deletedNodeId,
    );
    const cleanedCanvas =
      removedOutgoingEdges.length > 0
        ? cleanTargetDataForRemovedEdges({
            canvas: activeCanvas,
            removedEdges: removedOutgoingEdges,
            t,
          })
        : activeCanvas;
    const cleanedNodesById = new Map(
      cleanedCanvas.nodes.map((node) => [node.id, node]),
    );
    const updated = {
      ...result.canvas,
      nodes: result.canvas.nodes.map(
        (node) => cleanedNodesById.get(node.id) ?? node,
      ),
    };
    setDeletedNodeSnapshot(result.snapshot);
    setActiveCanvas(updated);
    setCanvases((prev) =>
      prev.map((canvas) => (canvas.id === updated.id ? updated : canvas)),
    );
    setContextMenu(null);
    setCanvasContextMenu(null);
    setPortMenu(null);
    setSelectedNodeId(result.nextSelectedNodeId);
    setTextModelMenuNodeId(null);
    setImageComposerMenu(null);
    setVideoComposerMenu(null);
  };

  const handleUndoDelete = () => {
    if (!activeCanvas || !deletedNodeSnapshot) return;
    const result = restoreDeletedCanvasNode({
      canvas: activeCanvas,
      snapshot: deletedNodeSnapshot,
    });
    if (!result) {
      setDeletedNodeSnapshot(null);
      return;
    }
    const restored = result.canvas;
    setActiveCanvas(restored);
    setCanvases((prev) =>
      prev.map((canvas) => (canvas.id === restored.id ? restored : canvas)),
    );
    setSelectedNodeId(result.selectedNodeId);
    setDeletedNodeSnapshot(null);
    setContextMenu(null);
  };

  const commitCanvas = (updated: AigcCanvas) => {
    activeCanvasRef.current = updated;
    setActiveCanvas(updated);
    setCanvases((prev) =>
      prev.map((canvas) => (canvas.id === updated.id ? updated : canvas)),
    );
  };

  const handleOpenImageAnnotation = (node: AigcCanvasNode) => {
    if (!imageAnnotationSourcePreviewUrl(node)) return;
    setAnnotationEditorNodeId(node.id);
    setSelectedNodeId(node.id);
    setContextMenu(null);
    setCanvasContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
    setImageComposerMenu(null);
    setVideoComposerMenu(null);
    setRailPanel(null);
  };

  const handleSaveImageAnnotation = (annotation: {
    annotationPreviewUrl: string;
    annotationPaths: ImageAnnotationPath[];
    annotationViewBox: {
      width: number;
      height: number;
    };
    instruction: string;
    sourcePreviewUrl: string;
  }) => {
    if (!activeCanvas || !annotationEditorNode) return;
    const result = createImageAnnotationCanvas({
      canvas: activeCanvas,
      sourceNode: annotationEditorNode,
      annotationPreviewUrl: annotation.annotationPreviewUrl,
      annotationPaths: annotation.annotationPaths,
      annotationViewBox: annotation.annotationViewBox,
      sourcePreviewUrl: annotation.sourcePreviewUrl,
      instruction: annotation.instruction,
    });
    commitCanvas(result.canvas);
    setSelectedNodeId(result.annotationNode.id);
    setAnnotationEditorNodeId(null);
  };

  const updateNodeData = (nodeId: string, data: Record<string, unknown>) => {
    setActiveCanvas((canvas) => {
      if (!canvas) return canvas;
      const updated = {
        ...canvas,
        nodes: canvas.nodes.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, ...data } }
            : node,
        ),
      };
      setCanvases((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      return updated;
    });
  };

  const handleOpenStyleLibrary = () => {
    if (!activeCanvas) return;
    const selectedImageNode =
      selectedNode?.type === "image_generate" &&
      !isStoryboardImageNode(selectedNode)
        ? selectedNode
        : null;
    const targetNode =
      selectedImageNode ??
      activeCanvas.nodes.find(
        (node) =>
          node.type === "image_generate" && !isStoryboardImageNode(node),
      ) ??
      null;

    if (targetNode) {
      setSelectedNodeId(targetNode.id);
      updateNodeData(targetNode.id, { activeTool: "style" });
      setRailPanel(null);
      setAddMenuOpen(false);
      closeCanvasMenus();
      closeExternalFloatingMenus();
      return;
    }

    const node = createNodeForType(
      t,
      "image_generate",
      activeCanvas.nodes.length,
    );
    const styleNode: AigcCanvasNode = {
      ...node,
      data: {
        ...node.data,
        activeTool: "style",
      },
    };
    commitCanvas(appendCanvasNodes(activeCanvas, [styleNode]));
    setSelectedNodeId(styleNode.id);
    setRailPanel(null);
    setAddMenuOpen(false);
    closeCanvasMenus();
    closeExternalFloatingMenus();
  };

  const handleDeleteCanvasEdge = (edgeId: string) => {
    if (!activeCanvas) return;
    const result = applyPortDisconnectionToCanvas({
      canvas: activeCanvas,
      edgeId,
      t,
    });
    if (!result) return;
    commitCanvas(result.canvas);
    setSelectedNodeId(result.selectedNodeId);
    setPortMenu(null);
    setContextMenu(null);
    setCanvasContextMenu(null);
    closeExternalFloatingMenus();
  };

  const {
    handleBeginGeneratedEdit,
    handleSelectTextModel,
    handleTextComposerSubmit,
    handleTextFormat,
    handleTextTry,
    handleToggleTextModelMenu,
  } = useTextNodeWorkflow({
    activeCanvas,
    commitCanvas,
    updateNodeData,
    setSelectedNodeId,
    setEditingTextNodeId,
    setTextModelMenuNodeId,
    setContextMenu,
    runTextNode: runNode,
    runCreatedNode: runNode,
    t,
  });

  const imageWorkflow = useImageNodeWorkflow({
    activeCanvas,
    commitCanvas,
    updateNodeData,
    setSelectedNodeId,
    modelOptions: capabilities,
    t,
    createAssetPreviewUrl,
    uploadAsset: aigcStudioApi.uploadAsset,
    onAnnotateGeneratedImage: handleOpenImageAnnotation,
    getGeneratedImageResultsLayoutData: (node) =>
      imageResultsExpansionData(node, {
        viewport: activeCanvas?.viewport,
        viewportScale,
        visibleWidth: canvasSurfaceSize.visibleWidth,
        visibleHeight: canvasSurfaceSize.visibleHeight,
      }),
  });

  const videoWorkflow = useVideoNodeWorkflow({
    activeCanvas,
    commitCanvas,
    updateNodeData,
    setSelectedNodeId,
    modelOptions: capabilities,
    t,
    createAssetPreviewUrl,
    uploadAsset: aigcStudioApi.uploadAsset,
    onRunNode: runNode,
  });

  const audioWorkflow = useAudioNodeWorkflow({
    updateNodeData,
    modelOptions: capabilities,
  });

  const directorStageWorkflow = useDirectorStageWorkflow({
    activeCanvas,
    commitCanvas,
    setSelectedNodeId,
    updateNodeData,
    uploadAsset: aigcStudioApi.uploadAsset,
    t,
  });

  const storyboardWorkflow = useStoryboardWorkflow({
    activeCanvas,
    commitCanvas,
    updateNodeData,
    setActiveCanvas,
    setCanvases,
    setSelectedNodeId,
    setTextModelMenuNodeId,
    setImageComposerMenu,
    setVideoComposerMenu,
    setPortMenu,
    nodeVisualWidth,
    connectCanvasNodes,
    modelOptions: capabilities,
    t,
  });

  const scriptWorkflow = useScriptNodeWorkflow({
    activeCanvas,
    updateNodeData,
    setActiveCanvas,
    setCanvases,
    setSelectedNodeId,
    setAddMenuOpen,
    setContextMenu,
    setCanvasContextMenu,
    setQuickTemplateMenu,
    setPortMenu,
    setTextModelMenuNodeId,
    setImageComposerMenu,
    setVideoComposerMenu,
    connectCanvasNodes,
    runScriptNode: runNode,
    runAssetImageNode: runNode,
    storyboardWorkflow,
    t,
  });

  const handleSaveNodeAsset = () => {
    if (!contextMenuNode) return;
    updateNodeData(contextMenuNode.id, {
      savedToAssets: true,
      savedAt: Date.now(),
    });
    setRailPanel("assets");
    setContextMenu(null);
  };

  const handleCreateSubject = () => {
    if (!contextMenuNode) return;
    updateNodeData(contextMenuNode.id, {
      savedToSubjects: true,
      savedAt: Date.now(),
    });
    setRailPanel("assets");
    setContextMenu(null);
  };

  const handleCopyNode = () => {
    const nodeToCopy = contextMenuNode ?? selectedNode;
    if (!nodeToCopy) return;
    setClipboardNode(nodeToCopy);
    setContextMenu(null);
  };

  const handlePasteNode = () => {
    if (!activeCanvas || !clipboardNode) return;
    const result = pasteCanvasNode({
      canvas: activeCanvas,
      node: clipboardNode,
      suffix: `paste-${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`,
      fallbackTitle: translatedNodeType(t, clipboardNode.type),
    });
    commitCanvas(result.canvas);
    setSelectedNodeId(result.node.id);
    setContextMenu(null);
  };

  const handleDuplicateNode = () => {
    const nodeToDuplicate = contextMenuNode ?? selectedNode;
    if (!activeCanvas || !nodeToDuplicate) return;
    const result = duplicateCanvasNodeWithEdges({
      canvas: activeCanvas,
      node: nodeToDuplicate,
      suffix: `copy-${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`,
      fallbackTitle: translatedNodeType(t, nodeToDuplicate.type),
    });
    commitCanvas(result.canvas);
    setSelectedNodeId(result.node.id);
    setContextMenu(null);
  };

  const handleUseAssetRecord = (record: CanvasAssetRecord) => {
    if (!activeCanvas) return;
    const node = createAssetNodeFromRecord({
      record,
      nodeCount: activeCanvas.nodes.length,
    });
    const positionedNode = {
      ...node,
      position: defaultNodePositionInViewport({
        viewport: activeCanvas.viewport,
        scale: viewportScale,
        visibleWidth: canvasSurfaceSize.visibleWidth,
        visibleHeight: canvasSurfaceSize.visibleHeight,
        nodeWidth: nodeVisualWidth(node),
        nodeHeight: nodeVisualHeight(node),
        nodeCount: activeCanvas.nodes.length,
      }),
    };
    commitCanvas(appendCanvasNodes(activeCanvas, [positionedNode]));
    setSelectedNodeId(positionedNode.id);
    setRailPanel(null);
  };

  const updateViewportScale = (
    nextScale: number,
    anchorPoint?: CanvasPoint,
  ) => {
    const boundedScale = boundedViewportScale(nextScale);
    setViewportScale(boundedScale);
    setActiveCanvas((canvas) => {
      if (!canvas) return canvas;
      const surfacePoint = anchorPoint ?? {
        x: canvasSurfaceSize.visibleWidth / 2,
        y: canvasSurfaceSize.visibleHeight / 2,
      };
      const updated = {
        ...canvas,
        viewport: zoomViewportAroundSurfacePoint({
          viewport: canvas.viewport,
          surfacePoint,
          currentScale: viewportScale,
          nextScale: boundedScale,
        }),
      };
      setCanvases((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      return updated;
    });
  };

  const fitViewportToNodes = () => {
    if (!activeCanvas || activeCanvas.nodes.length === 0) return;
    const surfaceRect = canvasSurfaceRef.current?.getBoundingClientRect();
    const visibleWidth = surfaceRect?.width || 1200;
    const visibleHeight = surfaceRect?.height || 760;
    const nextViewport = fitCanvasViewportToNodes({
      canvas: activeCanvas,
      visibleWidth,
      visibleHeight,
    });
    if (!nextViewport) return;
    setViewportScale(nextViewport.zoom);
    commitCanvas({ ...activeCanvas, viewport: nextViewport });
  };

  const centerViewportOnSelectedNode = () => {
    if (!selectedNode) return;
    centerViewportOnNode(selectedNode);
  };

  const centerViewportOnNode = (node: AigcCanvasNode) => {
    if (!activeCanvas) return;
    const surfaceRect = canvasSurfaceRef.current?.getBoundingClientRect();
    const visibleWidth = surfaceRect?.width || 1200;
    const visibleHeight = surfaceRect?.height || 760;
    const nextViewport = centerCanvasViewportOnNode({
      canvas: activeCanvas,
      node,
      visibleWidth,
      visibleHeight,
      scale: viewportScale,
    });
    const updated = { ...activeCanvas, viewport: nextViewport };
    commitCanvas(updated);
    setSelectedNodeId(node.id);
  };

  const handleCanvasWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    if (!isCanvasViewportTarget(event.target)) return;
    event.preventDefault();
    if (event.metaKey || event.ctrlKey) {
      const surfacePoint = surfacePointFromClient(event.clientX, event.clientY);
      const nextScale = viewportScale * Math.exp(-event.deltaY * 0.002);
      updateViewportScale(nextScale, surfacePoint);
      return;
    }
    offsetViewport(-(event.deltaX || 0), -(event.deltaY || 0));
  };

  const handleCanvasMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!activeCanvas) return;
    if (!isCanvasViewportTarget(event.target)) return;
    const isPrimaryDrag = event.button === 0;
    const isMiddleDrag = event.button === 1;
    if (!isPrimaryDrag && !isMiddleDrag) return;
    event.preventDefault();
    closeFloatingMenus();
    setSelectedNodeId(null);
    setPanningCanvas({
      startClientX: event.clientX,
      startClientY: event.clientY,
      startViewportX: activeCanvas.viewport.x ?? 0,
      startViewportY: activeCanvas.viewport.y ?? 0,
    });
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (isTyping) return;

      const key = event.key.toLowerCase();
      const commandKey = event.metaKey || event.ctrlKey;

      if (event.key === " " || event.key === "Spacebar") {
        event.preventDefault();
        setSpacePressed(true);
        return;
      }

      if (commandKey && key === "c") {
        event.preventDefault();
        handleCopyNode();
        return;
      }

      if (commandKey && key === "v") {
        event.preventDefault();
        handlePasteNode();
        return;
      }

      if (commandKey && key === "d") {
        event.preventDefault();
        handleDuplicateNode();
        return;
      }

      if (commandKey && key === "z") {
        event.preventDefault();
        handleUndoDelete();
        return;
      }

      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        handleDeleteNode(selectedNodeId ?? undefined);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    activeCanvas,
    clipboardNode,
    contextMenuNode,
    deletedNodeSnapshot,
    selectedNode,
    selectedNodeId,
  ]);

  useEffect(() => {
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key === " " || event.key === "Spacebar") {
        setSpacePressed(false);
      }
    };

    window.addEventListener("keyup", handleKeyUp);
    return () => window.removeEventListener("keyup", handleKeyUp);
  }, []);

  useEffect(() => {
    if (!panningCanvas) return;

    const handleMouseMove = (event: MouseEvent) => {
      commitViewport(
        panCanvasViewport({
          currentViewport: activeCanvas?.viewport,
          panState: panningCanvas,
          clientX: event.clientX,
          clientY: event.clientY,
          fallbackScale: viewportScale,
        }),
      );
    };

    const handleMouseUp = () => {
      setPanningCanvas(null);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [activeCanvas?.viewport, panningCanvas, viewportScale]);

  useEffect(() => {
    if (!portDrag) return;

    const handleMouseMove = (event: MouseEvent) => {
      event.preventDefault();
      const point = surfacePointFromClient(event.clientX, event.clientY);
      const moved =
        Math.hypot(point.x - portDrag.startX, point.y - portDrag.startY) > 4;
      setPortDrag({
        ...portDrag,
        currentX: point.x,
        currentY: point.y,
        hasMoved: portDrag.hasMoved || moved,
      });
    };

    const handleMouseUp = (event: MouseEvent) => {
      event.preventDefault();
      const point = surfacePointFromClient(event.clientX, event.clientY);
      const releaseMoved =
        portDrag.hasMoved ||
        Math.hypot(point.x - portDrag.startX, point.y - portDrag.startY) > 4;
      if (releaseMoved) {
        suppressNextPortClickRef.current = false;
      }
      const anchorNode = activeCanvas?.nodes.find(
        (node) => node.id === portDrag.nodeId,
      );
      const dropNodeId = releaseMoved
        ? nodeIdFromClientPoint(event.clientX, event.clientY)
        : null;

      if (activeCanvas && dropNodeId) {
        const result = applyPortConnectionToCanvas({
          canvas: activeCanvas,
          anchorNodeId: portDrag.nodeId,
          dropNodeId,
          side: portDrag.side,
          t,
        });
        if (result) {
          commitCanvas(result.canvas);
          setSelectedNodeId(result.selectedNodeId);
          setPortMenu(null);
          closeExternalFloatingMenus();
          setPortDrag(null);
          return;
        }
      }

      if (anchorNode) {
        openPortMenuAtSurfacePoint(anchorNode, portDrag.side, point);
      }
      setPortDrag(null);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [activeCanvas, portDrag, t]);

  useEffect(() => {
    if (!draggingNode) return;

    const handleMouseMove = (event: MouseEvent) => {
      const nextPosition = dragNodePosition({
        dragState: draggingNode,
        clientX: event.clientX,
        clientY: event.clientY,
        viewportScale,
      });
      setActiveCanvas((canvas) => {
        if (!canvas) return canvas;
        const updated = {
          ...canvas,
          nodes: canvas.nodes.map((node) =>
            node.id === draggingNode.nodeId
              ? { ...node, position: nextPosition }
              : node,
          ),
        };
        setCanvases((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
        return updated;
      });
    };

    const handleMouseUp = () => {
      setDraggingNode(null);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [draggingNode, viewportScale]);

  const toggleImageComposerMenu = (nodeId: string, menu: ImageComposerMenu) => {
    setImageComposerMenu((current) =>
      current?.nodeId === nodeId && current.menu === menu
        ? null
        : { nodeId, menu },
    );
    setTextModelMenuNodeId(null);
    setVideoComposerMenu(null);
  };

  const toggleVideoComposerMenu = (nodeId: string, menu: VideoComposerMenu) => {
    setVideoComposerMenu((current) =>
      current?.nodeId === nodeId && current.menu === menu
        ? null
        : { nodeId, menu },
    );
    setTextModelMenuNodeId(null);
    setImageComposerMenu(null);
  };

  const handleSourceImageReplace = async (
    node: AigcCanvasNode,
    file?: File,
  ) => {
    if (!activeCanvas || !file) return;
    let asset: AigcAsset;
    try {
      asset = await aigcStudioApi.uploadAsset(file);
    } catch {
      return;
    }
    const assetPreviewUrl = String(asset.url ?? asset.path ?? "").trim();
    const updated = replaceSourceImageReferences({
      canvas: activeCanvas,
      sourceNodeId: node.id,
      assetName: asset.name || file.name,
      assetPreviewUrl,
    });
    commitCanvas(updated);
  };

  const isGenerationNode = selectedNode
    ? ![
        "prompt",
        "reference_asset",
        "reference_note",
        "long_image_export",
        "output",
        "director_stage",
      ].includes(selectedNode.type)
    : false;

  const selectedNodeDefinition = selectedNode
    ? nodeDefinition(selectedNode.type)
    : undefined;

  const autoSaveStatusText = {
    saved: t("aigcStudio.autoSave.saved", "已自动保存"),
    dirty: t("aigcStudio.autoSave.dirty", "有未保存更改"),
    saving: t("aigcStudio.autoSave.saving", "保存中..."),
    error: t("aigcStudio.autoSave.error", "保存失败"),
  }[autoSaveStatus];

  const AutoSaveIcon =
    autoSaveStatus === "saving"
      ? Loader2
      : autoSaveStatus === "error"
      ? AlertCircle
      : CheckCircle2;

  const submitGuidedAsset = async () => {
    const currentTask = guide.task;
    if (!currentTask) {
      antdMessage.error("当前素材任务已失效，请从会话卡片重新进入");
      return false;
    }
    const outputNodeId =
      currentTask.binding.output_node_id ?? currentTask.binding.node_id;
    const blueprint = currentTask.workflow?.blueprint as
      | { review_node_ids?: string[] }
      | undefined;
    const declared = blueprint?.review_node_ids ?? [];
    const reviewAssets =
      activeCanvas && declared.length
        ? resolveWorkflowReviewAssets(
            activeCanvas.nodes,
            activeCanvas.edges,
            declared.map((id) => currentTask.binding.node_bindings?.[id] ?? ""),
          )
        : undefined;
    const assetId =
      reviewAssets?.[0]?.asset_id ??
      (activeCanvas
        ? resolveWorkflowOutputAssetId(
            activeCanvas.nodes,
            activeCanvas.edges,
            outputNodeId,
          )
        : "");
    if (!assetId) {
      antdMessage.error("当前绑定节点还没有可提交的成品");
      return false;
    }
    if (activeCanvas?.id !== currentTask.binding.canvas_id) return false;
    await submitGuidedTaskAsset(currentTask, assetId, reviewAssets);
    // Submission already persisted; a projection refresh failure must not undo it.
    await guide.refresh().catch(() => undefined);
    antdMessage.success("素材已提交，专家将按当前业务阶段审核");
    return true;
  };

  const performManualGuideStep = async (
    step: import("../../api/modules/superExpertPlatform").AigcGuideStepProjection,
  ) => {
    if (!activeCanvas || activeCanvas.id !== guide.task?.binding.canvas_id) {
      throw new Error("BOUND_CANVAS_MISMATCH");
    }
    let updated = activeCanvas;
    if (step.manual_action === "ADD_NODE") {
      if (!step.node_id || !step.node_kind)
        throw new Error("MANUAL_NODE_INVALID");
      if (!activeCanvas.nodes.some((node) => node.id === step.node_id)) {
        const template = createNodeForType(
          t,
          step.node_kind,
          activeCanvas.nodes.length,
        );
        const node = {
          ...template,
          id: step.node_id,
          data: { ...template.data, ...(step.manual_node_data ?? {}) },
        };
        updated = { ...activeCanvas, nodes: [...activeCanvas.nodes, node] };
        setSelectedNodeId(node.id);
      }
    } else if (step.manual_action === "CONNECT_EDGE") {
      if (!step.source_node_id || !step.target_node_id) {
        throw new Error("MANUAL_EDGE_INVALID");
      }
      const nodes = new Set(activeCanvas.nodes.map((node) => node.id));
      if (!nodes.has(step.source_node_id) || !nodes.has(step.target_node_id)) {
        throw new Error("MANUAL_EDGE_NODE_MISSING");
      }
      if (
        !activeCanvas.edges.some(
          (edge) =>
            edge.source === step.source_node_id &&
            edge.target === step.target_node_id &&
            String(edge.data?.role ?? "") === String(step.target_slot ?? ""),
        )
      ) {
        const edge = {
          ...connectCanvasNodes(step.source_node_id, step.target_node_id),
          id: `guide-${step.step_id}`,
          data: { role: step.target_slot ?? "" },
        };
        updated = { ...activeCanvas, edges: [...activeCanvas.edges, edge] };
      }
    } else {
      throw new Error("MANUAL_ACTION_UNSUPPORTED");
    }
    commitCanvas(updated);
    await persistCanvas(updated);
    await guide.refresh();
  };

  const legacyGuideCompletion = useMemo(
    () =>
      guide.task
        ? getAigcGuideStepCompletion({ task: guide.task, activeCanvas, jobs })
        : {},
    [activeCanvas, guide.task, jobs],
  );

  if (loading) {
    return <Spin style={{ display: "block", margin: "20vh auto" }} />;
  }

  return (
    <div className={styles.studio} data-platform-control-id="nav.aigc-studio">
      <aside className={styles.sidebar}>
        <div className={styles.title}>
          {t("aigcStudio.title", "AIGC 创意工作室")}
        </div>
        <div className={styles.subtitle}>
          {t(
            "aigcStudio.subtitle",
            "用于提示词、图片、视频和分镜流程的无限画布。",
          )}
        </div>
        <Button icon={<Plus size={14} />} onClick={handleCreateCanvas} block>
          {t("aigcStudio.newCanvas", "新建画布")}
        </Button>

        <div className={styles.sectionTitle}>
          {t("aigcStudio.canvases", "画布")}
        </div>
        <div className={styles.canvasList}>
          {canvases.map((canvas) => (
            <button
              type="button"
              key={canvas.id}
              className={`${styles.canvasItem} ${
                activeCanvas?.id === canvas.id ? styles.canvasItemActive : ""
              }`}
              onClick={() => void handleSelectCanvas(canvas)}
            >
              <strong>{canvas.name}</strong>
              <div className={styles.muted}>
                {t("aigcStudio.nodeCount", "{{count}} 个节点", {
                  count: canvas.nodes.length,
                })}
              </div>
            </button>
          ))}
        </div>

        <div className={styles.sectionTitle}>
          {t("aigcStudio.palette", "节点面板")}
        </div>
        <div className={styles.nodePalette}>
          {NODE_DEFINITIONS.filter((item) => isSidebarNodeType(item.type)).map(
            (definition) => (
              <button
                type="button"
                className={styles.nodeType}
                key={definition.type}
                data-platform-control-id={`aigc.canvas.add-node.${definition.type}`}
                onClick={() => handleAddNode(definition.type)}
              >
                {definition.icon} {translatedNodeType(t, definition.type)}
              </button>
            ),
          )}
        </div>
      </aside>

      <main className={styles.viewport}>
        <div className={styles.toolbar}>
          <div className={styles.toolbarLeft}>
            <MousePointer2 size={16} />
            <div className={styles.projectSwitcher}>
              <Input
                value={activeCanvas?.name ?? ""}
                onChange={(event) => updateCanvasName(event.target.value)}
                className={styles.canvasName}
              />
              <button
                type="button"
                className={styles.projectMenuButton}
                data-platform-control-id="aigc.canvas.create"
                aria-label={t("aigcStudio.projects.open", "打开项目列表")}
                onClick={(event) => {
                  event.stopPropagation();
                  setProjectMenuOpen((open) => !open);
                }}
              >
                <ChevronDown size={14} />
              </button>
              {projectMenuOpen && (
                <div
                  className={styles.projectMenu}
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className={styles.projectMenuHeader}>
                    <strong>{t("aigcStudio.projects.title", "项目")}</strong>
                    <button type="button" onClick={handleCreateCanvas}>
                      <Plus size={14} />
                      {t("aigcStudio.projects.new", "新建项目")}
                    </button>
                  </div>
                  <div className={styles.projectList}>
                    {canvases.map((canvas) => (
                      <div
                        key={canvas.id}
                        className={`${styles.projectItem} ${
                          activeCanvas?.id === canvas.id
                            ? styles.projectItemActive
                            : ""
                        }`}
                      >
                        <button
                          type="button"
                          className={styles.projectSelect}
                          onClick={() => void handleSelectCanvas(canvas)}
                        >
                          <strong>{canvas.name}</strong>
                          <small>
                            {t("aigcStudio.nodeCount", "{{count}} 个节点", {
                              count: canvas.nodes.length,
                            })}
                          </small>
                        </button>
                        {activeCanvas?.id === canvas.id && (
                          <em>{t("aigcStudio.projects.current", "当前")}</em>
                        )}
                        <button
                          type="button"
                          className={styles.projectDelete}
                          aria-label={t(
                            "aigcStudio.projects.delete",
                            "删除项目 {{name}}",
                            { name: canvas.name },
                          )}
                          title={t(
                            "aigcStudio.projects.deleteTitle",
                            "删除项目",
                          )}
                          onClick={(event) =>
                            void handleDeleteCanvas(canvas, event)
                          }
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                    {canvases.length === 0 && (
                      <div className={styles.projectEmpty}>
                        {t("aigcStudio.projects.empty", "暂无项目")}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className={styles.toolbarRight}>
            <div
              className={`${styles.autoSaveStatus} ${
                styles[`autoSave_${autoSaveStatus}`]
              }`}
            >
              <AutoSaveIcon
                size={14}
                className={
                  autoSaveStatus === "saving" ? styles.statusSpin : undefined
                }
              />
              {autoSaveStatusText}
            </div>
            <Button
              className={styles.toolbarSaveButton}
              icon={<Save size={14} />}
              loading={saving}
              onClick={handleSave}
            >
              {t("common.save", "保存")}
            </Button>
            <Button
              className={styles.toolbarRunButton}
              type="primary"
              icon={<Play size={14} />}
              loading={selectedNodeRunning}
              onClick={handleRunNode}
              disabled={
                !selectedNode ||
                !selectedNodeUsesModel ||
                !selectedNodeModel ||
                selectedNodeRunning
              }
            >
              {t("aigcStudio.runNode", "运行节点")}
            </Button>
          </div>
        </div>

        <div
          className={`${styles.canvasSurface} ${
            panningCanvas
              ? styles.canvasSurfacePanning
              : spacePressed
              ? styles.canvasSurfacePanReady
              : ""
          }`}
          data-testid="aigc-canvas-surface"
          ref={canvasSurfaceRef}
          onClick={() => {
            setContextMenu(null);
            setCanvasContextMenu(null);
            setQuickTemplateMenu(null);
            setAddMenuAnchor(null);
            setPortMenu(null);
            setTextModelMenuNodeId(null);
            setImageComposerMenu(null);
            setVideoComposerMenu(null);
            setProjectMenuOpen(false);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleCanvasDrop}
          onMouseDown={handleCanvasMouseDown}
          onWheel={handleCanvasWheel}
          onDoubleClick={handleCanvasDoubleClick}
          onContextMenu={handleCanvasContextMenu}
        >
          <input
            ref={canvasImageInputRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onClick={(event) => event.stopPropagation()}
            onChange={handleCanvasFileInput}
          />
          <input
            ref={canvasVideoInputRef}
            type="file"
            accept="video/*"
            multiple
            hidden
            onClick={(event) => event.stopPropagation()}
            onChange={handleCanvasFileInput}
          />
          <input
            ref={canvasAudioInputRef}
            type="file"
            accept="audio/*"
            multiple
            hidden
            onClick={(event) => event.stopPropagation()}
            onChange={handleCanvasFileInput}
          />
          {canvasContextMenu && (
            <CanvasContextMenu
              menu={canvasContextMenu}
              clipboardNode={clipboardNode}
              t={t}
              onAddNodeAt={handleAddNodeAt}
              onUploadImage={() =>
                handleOpenCanvasUploadInput(
                  canvasImageInputRef.current,
                  canvasContextMenu.position,
                )
              }
              onUploadVideo={() =>
                handleOpenCanvasUploadInput(
                  canvasVideoInputRef.current,
                  canvasContextMenu.position,
                )
              }
              onUploadAudio={() =>
                handleOpenCanvasUploadInput(
                  canvasAudioInputRef.current,
                  canvasContextMenu.position,
                )
              }
              onPasteNode={handlePasteNode}
            />
          )}

          {quickTemplateMenu && (
            <CanvasQuickTemplateMenu
              menu={quickTemplateMenu}
              t={t}
              onTemplate={handleTemplateNode}
            />
          )}

          <CanvasEdgeLayer
            edgeLines={visibleEdgeLines}
            onDeleteEdge={handleDeleteCanvasEdge}
          />

          {!activeCanvas && (
            <CanvasEmptyProjectLauncher
              t={t}
              onCreateCanvas={handleCreateCanvas}
            />
          )}

          {activeCanvas?.nodes.length === 0 && (
            <CanvasTemplateLauncher t={t} onTemplate={handleTemplateNode} />
          )}

          {activeCanvas?.nodes.map((node) => (
            <div
              role="button"
              tabIndex={0}
              key={node.id}
              data-testid={`aigc-node-${node.id}`}
              data-aigc-node-id={node.id}
              className={`${styles.node} ${styles[`node_${node.type}`] ?? ""} ${
                selectedNodeId === node.id ? styles.nodeSelected : ""
              } ${
                node.type === "image_generate" &&
                (!node.data.previewKind || node.data.previewKind === "uploaded")
                  ? styles.nodeImageCanvas
                  : ""
              } ${
                node.data.previewKind === "uploaded_source" ||
                node.data.previewKind === "style_template"
                  ? styles.nodeUploadedAsset
                  : ""
              } ${
                node.data.previewKind === "image_capture_group"
                  ? styles.nodeImageCaptureGroup
                  : ""
              } ${
                node.type === "prompt" &&
                node.data.previewKind &&
                !isScriptSourceTextNode(node)
                  ? styles.nodePromptPreview
                  : ""
              } ${
                node.data.assetShape === "wide" ? styles.nodeVideoAsset : ""
              } ${
                node.type === "image_generate" &&
                node.data.imageMode === "upscale"
                  ? styles.nodeImageUpscaleTarget
                  : ""
              } ${
                node.type === "script_generate" &&
                node.data.scriptFullscreen === true
                  ? styles.nodeScriptFullscreen
                  : ""
              } ${
                node.data.previewKind === "storyboard_video_batch"
                  ? styles.nodeStoryboardVideoBatch
                  : ""
              }`}
              style={{
                left:
                  node.type === "script_generate" &&
                  node.data.scriptFullscreen === true
                    ? 28
                    : (activeCanvas?.viewport.x ?? 0) +
                      node.position.x * viewportScale,
                top:
                  node.type === "script_generate" &&
                  node.data.scriptFullscreen === true
                    ? 48
                    : (activeCanvas?.viewport.y ?? 0) +
                      node.position.y * viewportScale,
                transform:
                  node.type === "script_generate" &&
                  node.data.scriptFullscreen === true
                    ? "none"
                    : `scale(${viewportScale})`,
                transformOrigin: "top left",
                width:
                  node.type === "script_generate" &&
                  node.data.scriptFullscreen === true
                    ? "calc(100% - 72px)"
                    : nodeVisualWidth(
                        isExpandedImageResultsNode(node)
                          ? compactImageResultsNode(node)
                          : node,
                      ),
                height:
                  node.type === "script_generate" &&
                  node.data.scriptFullscreen === true
                    ? "calc(100% - 112px)"
                    : (node.type === "image_generate" &&
                        node.data.imageMode !== "upscale" &&
                        (!node.data.previewKind ||
                          node.data.previewKind === "uploaded")) ||
                      node.type === "video_generate"
                    ? nodeVisualHeight(
                        isExpandedImageResultsNode(node)
                          ? compactImageResultsNode(node)
                          : node,
                      )
                    : undefined,
                ...imageResultsExpansionStyle(node, {
                  viewport: activeCanvas?.viewport,
                  viewportScale,
                  visibleWidth: canvasSurfaceSize.visibleWidth,
                  visibleHeight: canvasSurfaceSize.visibleHeight,
                }),
              }}
              data-aigc-node
              data-image-results-expanded={
                isExpandedImageResultsNode(node) ? "true" : undefined
              }
              onClick={(event) => {
                event.stopPropagation();
                setSelectedNodeId(node.id);
                setContextMenu(null);
                setCanvasContextMenu(null);
                setQuickTemplateMenu(null);
                setPortMenu(null);
                setTextModelMenuNodeId(null);
                setImageComposerMenu(null);
                setVideoComposerMenu(null);
              }}
              onMouseDown={(event) => handleNodeMouseDown(event, node)}
              onContextMenu={(event) => handleNodeContextMenu(event, node.id)}
            >
              <button
                type="button"
                aria-label={t("aigcStudio.expandNode", "放大节点")}
                className={styles.nodeUpload}
                onClick={(event) => event.stopPropagation()}
              >
                <Maximize2 size={14} />
              </button>
              <CanvasNodeHandle
                nodeId={node.id}
                side="left"
                label={t(
                  "aigcStudio.port.addUpstream",
                  "为 {{title}} 添加上游节点",
                  {
                    title: String(
                      node.data.title ?? translatedNodeType(t, node.type),
                    ),
                  },
                )}
                onClick={(event) => handleOpenPortMenu(event, node, "left")}
                onMouseDown={(event) =>
                  handlePortHandleMouseDown(event, node, "left")
                }
              />
              <CanvasNodeHandle
                nodeId={node.id}
                side="right"
                label={t(
                  "aigcStudio.port.addDownstream",
                  "从 {{title}} 创建下游节点",
                  {
                    title: String(
                      node.data.title ?? translatedNodeType(t, node.type),
                    ),
                  },
                )}
                onClick={(event) => handleOpenPortMenu(event, node, "right")}
                onMouseDown={(event) =>
                  handlePortHandleMouseDown(event, node, "right")
                }
              />
              {node.type === "script_generate" ? (
                <ScriptNode
                  node={node}
                  selected={selectedNodeId === node.id}
                  currentModel={currentModelForCanvasNode(node)}
                  modelOptions={modelOptionsForNode(
                    capabilities,
                    node,
                    "text_to_image",
                  )}
                  t={t}
                  scriptWorkflow={scriptWorkflow}
                  storyboardWorkflow={storyboardWorkflow}
                  onUpdateNodeData={updateNodeData}
                />
              ) : node.type === "reference_note" ? (
                <ReferenceNoteNode
                  node={node}
                  icon={nodeIcon(node.type)}
                  t={t}
                  setSelectedNodeId={setSelectedNodeId}
                  onUpdateNodeData={updateNodeData}
                />
              ) : canRenderTextNode(node) ? (
                <TextNode
                  node={node}
                  selected={selectedNodeId === node.id}
                  editingNodeId={editingTextNodeId}
                  textModelMenuNodeId={textModelMenuNodeId}
                  currentModel={currentModelForCanvasNode(node)}
                  modelOptions={modelOptionsForCanvasNode(node)}
                  currentModelKey={currentModelKeyForCanvasNode(node)}
                  nodeIcon={nodeIcon}
                  t={t}
                  onFormat={handleTextFormat}
                  onTry={handleTextTry}
                  onUpdateNodeData={updateNodeData}
                  onBeginGeneratedEdit={handleBeginGeneratedEdit}
                  onToggleModelMenu={handleToggleTextModelMenu}
                  onSelectTextModel={handleSelectTextModel}
                  onSubmitComposer={handleTextComposerSubmit}
                />
              ) : node.data.previewKind === "image_capture_group" ? (
                <ImageCaptureGroupNode
                  node={node}
                  t={t}
                  workflow={imageWorkflow}
                />
              ) : node.data.previewKind === "script_asset_group" ? (
                <ScriptAssetGroupNode node={node} t={t} />
              ) : node.data.previewKind === "uploaded_source" ||
                node.data.previewKind === "style_template" ? (
                <UploadedAssetNode
                  node={node}
                  t={t}
                  onReplace={handleSourceImageReplace}
                  onUpdateNodeData={updateNodeData}
                />
              ) : isStoryboardImageNode(node) ? (
                <StoryboardImageNode
                  node={node}
                  selected={selectedNodeId === node.id}
                  t={t}
                  storyboardWorkflow={storyboardWorkflow}
                />
              ) : node.type === "image_generate" &&
                (!node.data.previewKind ||
                  node.data.previewKind === "uploaded") ? (
                <ImageNode
                  node={
                    imageProgressSimulation.progressOverrides[node.id] ===
                    undefined
                      ? node
                      : {
                          ...node,
                          data: {
                            ...node.data,
                            imageProgress:
                              imageProgressSimulation.progressOverrides[
                                node.id
                              ],
                          },
                        }
                  }
                  selected={selectedNodeId === node.id}
                  t={t}
                  workflow={imageWorkflow}
                />
              ) : node.type === "video_generate" &&
                node.data.previewKind === "storyboard_video_batch" ? (
                <StoryboardVideoBatchNode
                  node={node}
                  selected={selectedNodeId === node.id}
                  t={t}
                  storyboardWorkflow={storyboardWorkflow}
                />
              ) : node.type === "video_generate" ? (
                <VideoNode
                  node={
                    videoProgressSimulation.progressOverrides[node.id] ===
                    undefined
                      ? node
                      : {
                          ...node,
                          data: {
                            ...node.data,
                            videoProgress:
                              videoProgressSimulation.progressOverrides[
                                node.id
                              ],
                          },
                        }
                  }
                  selected={selectedNodeId === node.id}
                  t={t}
                  workflow={videoWorkflow}
                />
              ) : node.type === "long_image_export" && activeCanvas ? (
                <LongImageExportNode
                  node={node}
                  canvas={activeCanvas}
                  selected={selectedNodeId === node.id}
                  exporting={exportingLongImageNodeId === node.id}
                  t={t}
                  onExport={handleExportLongImage}
                />
              ) : node.type === "director_stage" && activeCanvas ? (
                <DirectorStageNode
                  node={node}
                  selected={selectedNodeId === node.id}
                  sourcePreviewUrl={directorStageSourcePreviewUrl(
                    activeCanvas,
                    node,
                  )}
                  t={t}
                  workflow={directorStageWorkflow}
                />
              ) : node.type === "audio_generate" ? (
                <AudioNode
                  node={node}
                  t={t}
                  onUpdateNodeData={updateNodeData}
                />
              ) : (
                <GenericNode
                  node={node}
                  icon={nodeIcon(node.type)}
                  translatedType={translatedNodeType(t, node.type)}
                  t={t}
                />
              )}
              {shouldRenderNodeOutputList(node) && (
                <div className={styles.outputList}>
                  {nodeOutputs(node).map((asset) => (
                    <AigcAssetOutput asset={asset} key={asset.id} />
                  ))}
                </div>
              )}
              {selectedNodeId === node.id &&
                node.type === "script_generate" &&
                scriptMode(node) !== "generating_script" &&
                scriptMode(node) !== "storyboard_image_generating" &&
                (scriptMode(node) === "storyboard_select" ? (
                  <StoryboardComposer
                    node={node}
                    t={t}
                    storyboardWorkflow={storyboardWorkflow}
                    onUpdateNodeData={updateNodeData}
                  />
                ) : scriptMode(node) === "storyboard_grid" ? (
                  <StoryboardVideoComposer
                    node={node}
                    t={t}
                    storyboardWorkflow={storyboardWorkflow}
                    onClose={() => setSelectedNodeId(null)}
                  />
                ) : (
                  <ScriptComposer
                    node={node}
                    currentModel={currentModelForCanvasNode(node)}
                    modelOptions={modelOptionsForCanvasNode(node)}
                    currentModelKey={currentModelKeyForCanvasNode(node)}
                    modelMenuNodeId={textModelMenuNodeId}
                    t={t}
                    scriptWorkflow={scriptWorkflow}
                    onUpdateNodeData={updateNodeData}
                    onToggleModelMenu={handleToggleTextModelMenu}
                    onSelectModel={handleSelectTextModel}
                  />
                ))}
              {selectedNodeId === node.id &&
                isStoryboardImageNode(node) &&
                storyboardImageMode(node) !== "select" &&
                (storyboardImageMode(node) === "grid" ? (
                  <StoryboardVideoComposer
                    node={node}
                    t={t}
                    storyboardWorkflow={storyboardWorkflow}
                    onClose={() => setSelectedNodeId(null)}
                  />
                ) : null)}
              {selectedNodeId === node.id &&
                node.type === "image_generate" &&
                !isStoryboardImageNode(node) &&
                (!node.data.previewKind ||
                  node.data.previewKind === "uploaded") && (
                  <ImageComposer
                    node={node}
                    imageComposerMenu={imageComposerMenu}
                    currentModel={currentModelForCanvasNode(node)}
                    modelOptions={modelOptionsForCanvasNode(node)}
                    currentModelKey={currentModelKeyForCanvasNode(node)}
                    referenceAssets={
                      activeCanvas
                        ? imageReferenceAssetsForNode(activeCanvas, node)
                        : []
                    }
                    t={t}
                    workflow={imageWorkflow}
                    disabled={isNodeRunning(node.id)}
                    onUpdateNodeData={updateNodeData}
                    onRunNode={handleRunImageComposerNode}
                    onToggleMenu={toggleImageComposerMenu}
                    onSelectModel={(model) => {
                      selectNodeModel(node, model);
                    }}
                    onCloseMenu={() => setImageComposerMenu(null)}
                  />
                )}
              {selectedNodeId === node.id &&
                node.type === "video_generate" &&
                node.data.previewKind !== "storyboard_video_batch" && (
                  <VideoComposer
                    node={node}
                    videoComposerMenu={videoComposerMenu}
                    currentModel={currentModelForCanvasNode(node)}
                    modelOptions={modelOptionsForCanvasNode(node)}
                    currentModelKey={currentModelKeyForCanvasNode(node)}
                    connectedInputs={
                      activeCanvas
                        ? videoConnectedInputsForNode(activeCanvas, node)
                        : undefined
                    }
                    referenceAssets={
                      activeCanvas
                        ? imageReferenceAssetsForNode(activeCanvas, node)
                        : []
                    }
                    t={t}
                    workflow={videoWorkflow}
                    disabled={isNodeRunning(node.id)}
                    onUpdateNodeData={updateNodeData}
                    onToggleMenu={toggleVideoComposerMenu}
                    onSelectModel={(model) => {
                      selectNodeModel(node, model, {
                        videoModel: model.model_name ?? model.model_id,
                      });
                    }}
                    onCloseMenu={() => setVideoComposerMenu(null)}
                  />
                )}
              {selectedNodeId === node.id && node.type === "audio_generate" && (
                <AudioComposer
                  node={node}
                  currentModel={currentModelForCanvasNode(node)}
                  modelOptions={modelOptionsForCanvasNode(node)}
                  t={t}
                  workflow={audioWorkflow}
                  disabled={
                    !selectedNode ||
                    !currentModelForCanvasNode(node) ||
                    isNodeRunning(node.id)
                  }
                  onUpdateNodeData={updateNodeData}
                  onRunNode={handleRunNode}
                />
              )}
              {selectedNodeId === node.id &&
                isGenerationNode &&
                !isWorkflowOnlyNodeType(node.type) &&
                node.type !== "video_generate" &&
                node.type !== "script_generate" &&
                node.type !== "audio_generate" &&
                !(
                  node.type === "image_generate" &&
                  (!node.data.previewKind ||
                    node.data.previewKind === "uploaded")
                ) && (
                  <div
                    className={styles.nodeComposer}
                    data-testid="aigc-node-composer"
                  >
                    <div className={styles.composerTools}>
                      <button type="button">
                        {t("aigcStudio.style", "风格")}
                      </button>
                      <button type="button">
                        {t("aigcStudio.mark", "标记")}
                      </button>
                      <button type="button">
                        {t("aigcStudio.camera", "镜头")}
                      </button>
                      {selectedNodeDefinition?.tag && (
                        <span className={styles.menuTag}>
                          {selectedNodeDefinition.tag}
                        </span>
                      )}
                    </div>
                    <div className={styles.promptPlaceholder}>
                      {t(
                        "aigcStudio.promptPlaceholder",
                        "描述你想要生成的画面内容，按呼出指令，@引用素材",
                      )}
                    </div>
                    <div className={styles.parameterBar}>
                      <span>
                        {String(
                          node.data.modelLabel ??
                            modelLabelForNode(
                              capabilities,
                              node,
                              capabilityForCanvasNode(node),
                              "",
                              effectiveDefaultForCapability(
                                capabilityDefaults,
                                capabilityForCanvasNode(node),
                              ),
                            ),
                        )}
                      </span>
                      <span>16:9</span>
                      <span>2K</span>
                      <span>{translatedCapability(t, selectedCapability)}</span>
                      <button
                        type="button"
                        className={styles.runCircle}
                        onClick={handleRunNode}
                        disabled={
                          !selectedNode ||
                          !currentModelForCanvasNode(node) ||
                          isNodeRunning(node.id)
                        }
                      >
                        <Play size={15} />
                      </button>
                    </div>
                  </div>
                )}
            </div>
          ))}

          {annotationEditorNode && annotationEditorSourcePreviewUrl && (
            <ImageAnnotationEditor
              node={annotationEditorNode}
              sourcePreviewUrl={annotationEditorSourcePreviewUrl}
              t={t}
              onCancel={() => setAnnotationEditorNodeId(null)}
              onSave={handleSaveImageAnnotation}
            />
          )}

          {portMenu && portMenuNode && (
            <CanvasPortMenu
              menu={portMenu}
              node={portMenuNode}
              t={t}
              onCreatePortNode={handleCreatePortNode}
            />
          )}

          {contextMenu && (
            <div
              role="menu"
              className={styles.contextMenu}
              style={{ left: contextMenu.x, top: contextMenu.y }}
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                role="menuitem"
                onClick={handleSaveNodeAsset}
              >
                <span>
                  <Package size={14} />
                  {t("aigcStudio.contextMenu.saveAsset", "保存到我的素材")}
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={
                  !contextMenuNode ||
                  ![
                    "image_generate",
                    "video_generate",
                    "reference_asset",
                  ].includes(contextMenuNode.type)
                }
                onClick={handleCreateSubject}
              >
                <span>
                  <Boxes size={14} />
                  {t("aigcStudio.contextMenu.createSubject", "创建主体")}
                </span>
              </button>
              <div className={styles.contextMenuDivider} />
              <button type="button" role="menuitem" onClick={handleCopyNode}>
                <span>
                  <Copy size={14} />
                  {t("aigcStudio.contextMenu.copyNode", "复制节点")}
                </span>
                <span>⌘C</span>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={handleDuplicateNode}
              >
                <span>
                  <Clipboard size={14} />
                  {t("aigcStudio.contextMenu.createScript", "创建副本")}
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={!clipboardNode}
                onClick={handlePasteNode}
              >
                <span>
                  <Clipboard size={14} />
                  {t("aigcStudio.contextMenu.paste", "粘贴")}
                </span>
                <span>⌘V</span>
              </button>
              <button
                type="button"
                role="menuitem"
                className={styles.contextMenuDanger}
                onClick={() => handleDeleteNode()}
              >
                <span>
                  <Trash2 size={14} />
                  {t("aigcStudio.contextMenu.delete", "删除")}
                </span>
                <span>⌘⌫</span>
              </button>
              <div className={styles.contextMenuDivider} />
              <button type="button" role="menuitem" onClick={handleCopyNode}>
                <span>
                  <Copy size={14} />
                  {t("aigcStudio.contextMenu.copyToClipboard", "复制到剪贴板")}
                </span>
              </button>
            </div>
          )}
        </div>
        <div
          className={styles.canvasChrome}
          data-testid="aigc-canvas-chrome"
          aria-label={t("aigcStudio.canvasControls", "画布控件")}
        >
          <CanvasRail
            railPanel={railPanel}
            t={t}
            onToggleAddMenu={() => {
              setAddMenuOpen((open) => !open);
              setAddMenuAnchor(null);
              setRailPanel(null);
            }}
            onSelectPanel={(panel) => {
              setRailPanel((activePanel) =>
                activePanel === panel ? null : panel,
              );
              setAddMenuOpen(false);
            }}
            onOpenStyleLibrary={handleOpenStyleLibrary}
          />

          {addMenuOpen && (
            <CanvasAddMenu
              anchor={addMenuAnchor}
              t={t}
              onAddNode={handleAddNode}
            />
          )}

          {railPanel && (
            <CanvasRailPanel
              railPanel={railPanel}
              assetRecords={assetRecords}
              subjectRecords={subjectRecords}
              historyRecords={historyRecords}
              t={t}
              onTemplate={handleTemplateNode}
              onUseAssetRecord={handleUseAssetRecord}
            />
          )}

          <CanvasMinimap
            minimapOpen={minimapOpen}
            viewportScale={viewportScale}
            viewport={
              activeCanvas?.viewport ?? { x: 0, y: 0, zoom: viewportScale }
            }
            visibleWidth={canvasSurfaceSize.visibleWidth}
            visibleHeight={canvasSurfaceSize.visibleHeight}
            nodes={activeCanvas?.nodes ?? []}
            selectedNode={selectedNode}
            selectedNodeId={selectedNodeId}
            canvasBounds={canvasBounds}
            t={t}
            onFitViewport={fitViewportToNodes}
            onCenterSelectedNode={centerViewportOnSelectedNode}
            onToggleMinimap={() => setMinimapOpen((open) => !open)}
            onUpdateViewportScale={updateViewportScale}
            onCenterNode={centerViewportOnNode}
            onMoveViewport={commitViewport}
          />
        </div>
      </main>

      <aside className={styles.inspector}>
        <div className={styles.title}>
          {t("aigcStudio.inspector", "检查器")}
        </div>
        {selectedNode ? (
          <>
            <div className={styles.muted}>
              {t("aigcStudio.selected", "已选：{{id}}", {
                id: selectedNode.id,
              })}
            </div>
            {selectedNodeUsesModel ? (
              <>
                <div className={styles.sectionTitle}>
                  {t("aigcStudio.capabilityTitle", "能力")}
                </div>
                <span className={styles.capabilityBadge}>
                  {translatedCapability(t, selectedCapability)}
                </span>
                <div className={styles.sectionTitle}>
                  {t("aigcStudio.model", "模型")}
                </div>
                <Select
                  value={selectedNodeModelKey}
                  style={{ width: "100%" }}
                  placeholder={t("aigcStudio.noModel", "暂无匹配模型")}
                  onChange={(value) => {
                    const model = selectedNodeModelOptions.find(
                      (item) => modelKey(item) === value,
                    );
                    if (selectedNode && model) {
                      selectNodeModel(selectedNode, model);
                    }
                  }}
                  options={selectedNodeModelOptions.map((item) => ({
                    value: `${item.provider_id}:${item.model_id}`,
                    label: `${item.provider_name} / ${item.model_name}${
                      selectedNodeModelState?.invalidSavedModel &&
                      modelKey(item) === selectedNodeModelKey
                        ? ` · ${t(
                            "aigcStudio.modelUnavailable",
                            "该模型已不可用",
                          )}`
                        : ""
                    }`,
                    disabled:
                      selectedNodeModelState?.invalidSavedModel &&
                      modelKey(item) === selectedNodeModelKey,
                  }))}
                />
                {selectedNodeModelState?.invalidSavedModel && (
                  <div style={{ color: "#d46b08", marginTop: 8 }}>
                    {t("aigcStudio.modelUnavailable", "该模型已不可用")}
                  </div>
                )}
              </>
            ) : (
              <>
                <div className={styles.sectionTitle}>
                  {t("aigcStudio.workflow", "工作流")}
                </div>
                <span className={styles.capabilityBadge}>
                  {t("aigcStudio.longImageExport.workflowOnly", "本地排版导出")}
                </span>
                <p className={styles.muted}>
                  {t(
                    "aigcStudio.longImageExport.workflowHint",
                    "不使用大模型；按连线顺序收集文本和图片，节点内导出完整长图和切片。",
                  )}
                </p>
              </>
            )}
          </>
        ) : (
          <Empty description={t("aigcStudio.noNode", "选择一个节点")} />
        )}

        <div className={styles.sectionTitle}>
          {t("aigcStudio.available", "可用能力")}
        </div>
        <div className={styles.capabilityList}>
          {capabilities.map((item) => (
            <div
              key={`${item.provider_id}-${item.model_id}-${item.capability}`}
              className={styles.capabilityCard}
            >
              <strong>{item.model_name}</strong>
              <span className={styles.capabilityBadge}>
                {translatedCapability(t, item.capability)}
              </span>
              <span className={styles.muted}>
                {item.provider_name} ·{" "}
                {t(
                  `aigcStudio.source.${item.source}`,
                  item.source === "plugin_tool" ? "插件工具" : "模型管理",
                )}
              </span>
            </div>
          ))}
          {capabilities.length === 0 && (
            <Empty
              description={t(
                "aigcStudio.emptyCapabilities",
                "还没有配置支持 AIGC 的模型。",
              )}
            />
          )}
        </div>

        <div className={styles.sectionTitle}>
          {t("aigcStudio.jobs", "任务")}
        </div>
        <div className={styles.jobs}>
          {jobs.map((job) => (
            <div className={styles.jobRow} key={job.id}>
              <strong>{translatedCapability(t, job.capability)}</strong>
              <div>
                <span className={styles.statusBadge}>
                  {t(
                    `aigcStudio.jobStatus.${job.status}`,
                    JOB_STATUS_FALLBACKS[job.status] ?? job.status,
                  )}
                </span>
              </div>
              <div className={styles.muted}>{job.model_id}</div>
              {job.outputs.map((asset) => (
                <AigcAssetOutput asset={asset} key={asset.id} />
              ))}
              <div className={styles.jobActions}>
                <Button size="small" onClick={() => handleCancelJob(job.id)}>
                  {t("aigcStudio.cancelJob", "取消")}
                </Button>
                <Button size="small" onClick={() => handleRetryJob(job.id)}>
                  {t("aigcStudio.retryJob", "重试")}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </aside>
      {guide.taskId && guide.error ? (
        <aside className={styles.guideLoadError} role="alert">
          AIGC 任务向导加载失败：{guide.error}
        </aside>
      ) : null}
      {guide.taskId && guide.task && guide.guide ? (
        <AigcGuidePanel
          task={guide.task}
          guide={guide.guide}
          activeCanvasId={activeCanvas?.id}
          onRefresh={guide.refresh}
          onManualBuild={performManualGuideStep}
          onFocusStep={(nodeId, controlId) => {
            const target = activeCanvas?.nodes.find(
              (node) => node.id === nodeId,
            );
            if (!target) {
              antdMessage.error("当前任务绑定的节点不可用，向导已停止推进");
              return;
            }
            centerViewportOnNode(target);
            window.setTimeout(() => {
              if (!focusPlatformControl(controlId, nodeId)) {
                antdMessage.error("当前步骤的操作按钮不可用，请刷新任务后重试");
              }
            }, 0);
          }}
          onSkipOptional={async (step) => {
            const currentTask = guide.task;
            if (!currentTask || !currentTask.binding.workflow_id) return;
            const eventStorageKey = `dclaw:aigc-guide-skip:${guide.taskId}:${
              step.step_id
            }:${guide.guide!.guide_revision}`;
            const eventId =
              localStorage.getItem(eventStorageKey) || crypto.randomUUID();
            localStorage.setItem(eventStorageKey, eventId);
            await superExpertPlatformApi.command("aigc.guide.update", {
              installation_id: currentTask.binding.installation_id,
              contract_version: "1",
              idempotency_key: eventId,
              arguments: {
                binding: currentTask.binding,
                event_id: eventId,
                guide: {
                  action: "SKIP_OPTIONAL",
                  workflow_id: currentTask.binding.workflow_id,
                  guide_revision: guide.guide!.guide_revision,
                  step_id: step.step_id,
                  logical_node_id: step.logical_node_id,
                  node_id: step.node_id,
                },
              },
            });
            await guide.refresh();
          }}
          onReturnToChat={returnToGuidedConversation}
          onSubmit={submitGuidedAsset}
        />
      ) : null}
      {guide.taskId && guide.task && guide.operation && !guide.guide ? (
        <LegacyAigcGuidePanel
          taskId={guide.taskId}
          task={guide.task}
          operation={guide.operation}
          activeCanvasId={activeCanvas?.id}
          stepCompletion={legacyGuideCompletion}
          onSubmit={submitGuidedAsset}
          onReturnToChat={returnToGuidedConversation}
        />
      ) : null}
    </div>
  );
}
