import { useCallback, type Dispatch, type SetStateAction } from "react";

import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { modelForNode } from "../../nodeModelSelection";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";
import {
  isStoryboardImageNode,
  scriptSelectedShotIds,
  scriptSelectedStoryboardVideoShotIds,
  scriptShotsFromNode,
  scriptStoryboardImageShotIds,
  type ScriptShot,
} from "../ScriptNode/scriptNodeState";

type UseStoryboardWorkflowArgs = {
  activeCanvas: AigcCanvas | null;
  commitCanvas: (canvas: AigcCanvas) => void;
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  setActiveCanvas: Dispatch<SetStateAction<AigcCanvas | null>>;
  setCanvases: Dispatch<SetStateAction<AigcCanvas[]>>;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  setTextModelMenuNodeId: Dispatch<SetStateAction<string | null>>;
  setImageComposerMenu: (value: null) => void;
  setVideoComposerMenu: (value: null) => void;
  setPortMenu: (value: null) => void;
  nodeVisualWidth: (node: AigcCanvasNode) => number;
  connectCanvasNodes: (source: string, target: string) => AigcCanvasEdge;
  modelOptions?: AigcCapabilityInfo[];
  t: Translate;
};

export function useStoryboardWorkflow({
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
  modelOptions = [],
  t,
}: UseStoryboardWorkflowArgs): StoryboardWorkflow {
  const closeComposerMenus = useCallback(() => {
    setTextModelMenuNodeId(null);
    setImageComposerMenu(null);
    setVideoComposerMenu(null);
    setPortMenu(null);
  }, [
    setImageComposerMenu,
    setPortMenu,
    setTextModelMenuNodeId,
    setVideoComposerMenu,
  ]);

  const finishStoryboardImageGeneration = useCallback(
    (nodeId: string) => {
      window.setTimeout(() => {
        setActiveCanvas((canvas) => {
          if (!canvas) return canvas;
          const updated = {
            ...canvas,
            nodes: canvas.nodes.map((item) => {
              if (item.id !== nodeId) return item;
              const shotIds = scriptStoryboardImageShotIds(item);
              return {
                ...item,
                data: {
                  ...item.data,
                  ...(isStoryboardImageNode(item)
                    ? {
                        storyboardImageMode: "grid",
                        previewKind: "storyboard_image_batch",
                        storyboardGroupStatus: "ready",
                      }
                    : {
                        scriptMode: "storyboard_grid",
                      }),
                  selectedStoryboardShotId: shotIds[0] ?? null,
                  selectedStoryboardVideoShotIds: shotIds,
                  storyboardImageProgress: 100,
                },
              };
            }),
          };
          setCanvases((prev) =>
            prev.map((item) => (item.id === updated.id ? updated : item)),
          );
          return updated;
        });
      }, 420);
    },
    [setActiveCanvas, setCanvases],
  );

  const storyboardImageNodeIdForShot = useCallback(
    (scriptNodeId: string, shotId: string) =>
      `storyboard-image-${scriptNodeId}-${shotId.replace(
        /[^a-zA-Z0-9_-]+/g,
        "-",
      )}`,
    [],
  );

  const buildStoryboardImageNode = useCallback(
    ({
      existingNode,
      sourceNode,
      shot,
      index,
    }: {
      existingNode?: AigcCanvasNode;
      sourceNode: AigcCanvasNode;
      shot: ScriptShot;
      index: number;
    }): AigcCanvasNode => {
      const nodeId = storyboardImageNodeIdForShot(sourceNode.id, shot.id);
      const styleName = String(sourceNode.data.storyboardStyle ?? "Lib Image");
      return {
        id: nodeId,
        type: "image_generate",
        position:
          existingNode?.position ?? {
            x: sourceNode.position.x + nodeVisualWidth(sourceNode) + 120,
            y: sourceNode.position.y + index * 220,
          },
        data: {
          ...(existingNode?.data ?? {}),
          title: t(
            "aigcStudio.scriptNode.storyboardShotImageTitle",
            "分镜图 {{no}}",
            { no: shot.no },
          ),
          text: shot.prompt,
          composerText: shot.prompt,
          imageMode: "text_to_image",
          previewKind: "image_generate",
          sourceScriptNodeId: sourceNode.id,
          sourceShotId: shot.id,
          storyboardShotNo: shot.no,
          storyboardStyle: styleName,
          aspectRatio: sourceNode.data.storyboardAspectRatio ?? "自适应",
          resolution: sourceNode.data.storyboardResolution ?? "2K",
          imageCount: 1,
          inputUpdated: true,
        },
      };
    },
    [nodeVisualWidth, storyboardImageNodeIdForShot, t],
  );

  const createOrUpdateStoryboardImageNode = useCallback(
    (node: AigcCanvasNode) => {
      if (!activeCanvas) return null;
      const shots = scriptShotsFromNode(node);
      const shotIds = scriptSelectedShotIds(node);
      const selectedShots = shots.filter((shot) => shotIds.includes(shot.id));
      if (!selectedShots.length) return null;
      const storyboardNodes = selectedShots.map((shot, index) => {
        const nodeId = storyboardImageNodeIdForShot(node.id, shot.id);
        return buildStoryboardImageNode({
          existingNode: activeCanvas.nodes.find((item) => item.id === nodeId),
          sourceNode: node,
          shot,
          index,
        });
      });
      const storyboardNodeIds = storyboardNodes.map((item) => item.id);
      const existingStoryboardNodeIds = new Set(
        activeCanvas.nodes.map((item) => item.id),
      );
      const storyboardNodeById = new Map(
        storyboardNodes.map((item) => [item.id, item]),
      );
      const existingEdgeKeys = new Set(
        activeCanvas.edges.map((edge) => `${edge.source}:${edge.target}`),
      );
      const newEdges = storyboardNodes
        .filter((item) => !existingEdgeKeys.has(`${node.id}:${item.id}`))
        .map((item) => connectCanvasNodes(node.id, item.id));
      const updated: AigcCanvas = {
        ...activeCanvas,
        nodes: activeCanvas.nodes
          .map((item) => {
            if (item.id === node.id) {
              return {
                ...item,
                data: {
                  ...item.data,
                  scriptMode: "script_ready",
                  scriptView: "script",
                  scriptWorkflowStep: "prompts",
                  selectedShotIds: shotIds,
                  storyboardBatchDialogOpen: false,
                  storyboardStyleMenuOpen: false,
                  storyboardImageNodeIds: storyboardNodeIds,
                  storyboardImageShotIds: shotIds,
                  selectedStoryboardShotId: shotIds[0] ?? null,
                  selectedStoryboardVideoShotIds: shotIds,
                },
              };
            }
            return storyboardNodeById.get(item.id) ?? item;
          })
          .concat(
            storyboardNodes.filter(
              (item) => !existingStoryboardNodeIds.has(item.id),
            ),
          ),
        edges: [...activeCanvas.edges, ...newEdges],
      };
      commitCanvas(updated);
      setSelectedNodeId(storyboardNodeIds[0] ?? node.id);
      closeComposerMenus();
      return storyboardNodeIds[0] ?? null;
    },
    [
      activeCanvas,
      buildStoryboardImageNode,
      closeComposerMenus,
      commitCanvas,
      connectCanvasNodes,
      setSelectedNodeId,
      storyboardImageNodeIdForShot,
    ],
  );

  const handleCloseStoryboardComposer = useCallback(
    (node: AigcCanvasNode) => {
      if (isStoryboardImageNode(node)) {
        updateNodeData(node.id, { storyboardStyleMenuOpen: false });
        setSelectedNodeId(null);
        return;
      }
      updateNodeData(node.id, {
        scriptMode: "script_ready",
        selectedShotIds: scriptSelectedShotIds(node),
        storyboardBatchDialogOpen: false,
        storyboardStyleMenuOpen: false,
      });
    },
    [setSelectedNodeId, updateNodeData],
  );

  const handleStoryboardComposerSubmit = useCallback(
    (node: AigcCanvasNode) => {
      if (!isStoryboardImageNode(node)) {
        createOrUpdateStoryboardImageNode(node);
        return;
      }
      const shotIds = scriptSelectedShotIds(node);
      updateNodeData(node.id, {
        storyboardImageMode: "generating",
        previewKind: "storyboard_image_batch",
        storyboardImageShotIds: shotIds,
        selectedStoryboardShotId: null,
        selectedStoryboardVideoShotIds: shotIds,
        storyboardStyleMenuOpen: false,
        storyboardImageProgress: 4,
      });
      finishStoryboardImageGeneration(node.id);
    },
    [
      createOrUpdateStoryboardImageNode,
      finishStoryboardImageGeneration,
      updateNodeData,
    ],
  );

  const handleRunStoryboardImageGroup = useCallback(
    (node: AigcCanvasNode) => {
      const shotIds = scriptStoryboardImageShotIds(node);
      if (!shotIds.length) return;
      updateNodeData(node.id, {
        storyboardImageMode: "generating",
        previewKind: "storyboard_image_batch",
        selectedStoryboardShotId: null,
        selectedStoryboardVideoShotIds: shotIds,
        storyboardImageProgress: 6,
        storyboardGroupStatus: "generating",
      });
      finishStoryboardImageGeneration(node.id);
    },
    [finishStoryboardImageGeneration, updateNodeData],
  );

  const handleToggleScriptShot = useCallback(
    (node: AigcCanvasNode, shotId: string, checked: boolean) => {
      const current = new Set(scriptSelectedShotIds(node));
      if (checked) {
        current.add(shotId);
      } else {
        current.delete(shotId);
      }
      updateNodeData(node.id, { selectedShotIds: Array.from(current) });
    },
    [updateNodeData],
  );

  const handleToggleAllScriptShots = useCallback(
    (node: AigcCanvasNode, checked: boolean) => {
      updateNodeData(node.id, {
        selectedShotIds: checked
          ? scriptShotsFromNode(node).map((shot) => shot.id)
          : [],
      });
    },
    [updateNodeData],
  );

  const handleSelectStoryboardStyle = useCallback(
    (node: AigcCanvasNode, styleName: string) => {
      updateNodeData(node.id, {
        storyboardStyle: styleName,
        storyboardStyleMenuOpen: false,
      });
    },
    [updateNodeData],
  );

  const handleSelectStoryboardShot = useCallback(
    (node: AigcCanvasNode, shot: ScriptShot) => {
      updateNodeData(node.id, { selectedStoryboardShotId: shot.id });
    },
    [updateNodeData],
  );

  const handleToggleStoryboardVideoShot = useCallback(
    (node: AigcCanvasNode, shotId: string, checked: boolean) => {
      const current = new Set(scriptSelectedStoryboardVideoShotIds(node));
      if (checked) {
        current.add(shotId);
      } else {
        current.delete(shotId);
      }
      updateNodeData(node.id, {
        selectedStoryboardVideoShotIds: Array.from(current),
      });
    },
    [updateNodeData],
  );

  const handleToggleAllStoryboardVideoShots = useCallback(
    (node: AigcCanvasNode, checked: boolean) => {
      updateNodeData(node.id, {
        selectedStoryboardVideoShotIds: checked
          ? scriptStoryboardImageShotIds(node)
          : [],
      });
    },
    [updateNodeData],
  );

  const handleOpenStoryboardVideoDialog = useCallback(
    (node: AigcCanvasNode) => {
      const selectedIds = scriptSelectedStoryboardVideoShotIds(node);
      const selectedVideoModel = modelForNode(
        modelOptions,
        node,
        "text_to_video",
      );
      const currentModelLabel =
        selectedVideoModel?.model_name ?? selectedVideoModel?.model_id;
      updateNodeData(node.id, {
        storyboardVideoDialogOpen: true,
        storyboardVideoDialogPending: false,
        selectedStoryboardVideoShotIds: selectedIds,
        storyboardVideoModel: currentModelLabel,
        storyboardVideoProviderId: selectedVideoModel?.provider_id,
        storyboardVideoModelId: selectedVideoModel?.model_id,
        storyboardVideoModelCapability: selectedVideoModel?.capability,
      });
      closeComposerMenus();
    },
    [closeComposerMenus, modelOptions, updateNodeData],
  );

  const handleCloseStoryboardVideoDialog = useCallback(
    (node: AigcCanvasNode) => {
      updateNodeData(node.id, {
        storyboardVideoDialogOpen: false,
        storyboardVideoDialogPending: false,
      });
    },
    [updateNodeData],
  );

  const handleGenerateStoryboardVideos = useCallback(
    (node: AigcCanvasNode) => {
      if (!activeCanvas) return;
      const selectedIds = scriptSelectedStoryboardVideoShotIds(node);
      if (!selectedIds.length) return;
      const shots = scriptShotsFromNode(node).filter((shot) =>
        selectedIds.includes(shot.id),
      );
      const selectedVideoModel = modelForNode(
        modelOptions,
        node,
        "text_to_video",
      );
      const currentModelLabel =
        selectedVideoModel?.model_name ?? selectedVideoModel?.model_id;
      updateNodeData(node.id, { storyboardVideoDialogPending: true });
      window.setTimeout(() => {
        const existingVideoNodeId =
          typeof node.data.storyboardVideoNodeId === "string"
            ? node.data.storyboardVideoNodeId
            : "";
        const sourceStoryboardNode =
          typeof node.data.storyboardImageNodeId === "string"
            ? activeCanvas.nodes.find(
                (item) => item.id === node.data.storyboardImageNodeId,
              )
            : null;
        const sourceNode = sourceStoryboardNode ?? node;
        const videoNodeId =
          existingVideoNodeId ||
          `storyboard-video-${Date.now().toString(36)}-${
            activeCanvas.nodes.length + 1
          }`;
        const videoNode: AigcCanvasNode = {
          id: videoNodeId,
          type: "video_generate",
          position: {
            x: sourceNode.position.x + nodeVisualWidth(sourceNode) + 120,
            y: sourceNode.position.y,
          },
          data: {
            title: t(
              "aigcStudio.scriptNode.videoGroupTitle",
              "视频组 · {{title}}-视频组",
              {
                title: String(
                  node.data.scriptPrompt ??
                    node.data.title ??
                    t("aigcStudio.nodeType.script_generate", "脚本生成器"),
                ),
              },
            ),
            text: t(
              "aigcStudio.scriptNode.videoBatchDescription",
              "根据已生成的分镜图批量生成视频片段。",
            ),
            previewKind: "storyboard_video_batch",
            sourceScriptNodeId: node.id,
            sourceStoryboardImageNodeId: sourceStoryboardNode?.id ?? null,
            videoBatchShots: shots,
            videoModel: currentModelLabel,
            modelLabel: currentModelLabel,
            providerId: selectedVideoModel?.provider_id,
            modelId: selectedVideoModel?.model_id,
            modelCapability: selectedVideoModel?.capability,
            aspectRatio: node.data.storyboardVideoAspectRatio ?? "16:9",
            resolution: node.data.storyboardVideoResolution ?? "720P",
            videoDuration: node.data.storyboardVideoDuration ?? 5,
            videoBatchStatus: "idle",
            videoBatchProgress: null,
            videoBatchRunningCount: 0,
            videoBatchFailedShotIds: [],
          },
        };
        const hasVideoNode = activeCanvas.nodes.some(
          (item) => item.id === videoNodeId,
        );
        const hasEdge = activeCanvas.edges.some(
          (edge) =>
            edge.source === sourceNode.id && edge.target === videoNodeId,
        );
        const updated: AigcCanvas = {
          ...activeCanvas,
          nodes: activeCanvas.nodes
            .map((item) =>
              item.id === node.id
                ? {
                    ...item,
                    data: {
                      ...item.data,
                      storyboardVideoDialogOpen: false,
                      storyboardVideoDialogPending: false,
                      storyboardVideoNodeId: videoNodeId,
                    },
                  }
                : item.id === videoNodeId
                ? {
                    ...videoNode,
                    position: item.position,
                  }
                : item,
            )
            .concat(hasVideoNode ? [] : [videoNode]),
          edges: hasEdge
            ? activeCanvas.edges
            : [
                ...activeCanvas.edges,
                connectCanvasNodes(sourceNode.id, videoNodeId),
              ],
        };
        commitCanvas(updated);
        setSelectedNodeId(videoNodeId);
        closeComposerMenus();
      }, 120);
    },
    [
      activeCanvas,
      closeComposerMenus,
      commitCanvas,
      connectCanvasNodes,
      nodeVisualWidth,
      setSelectedNodeId,
      t,
      updateNodeData,
    ],
  );

  const handleRunStoryboardVideoGroup = useCallback(
    (node: AigcCanvasNode) => {
      const shots = Array.isArray(node.data.videoBatchShots)
        ? (node.data.videoBatchShots as ScriptShot[])
        : [];
      if (!shots.length) return;
      const runningCount = Math.min(3, shots.length);
      const failedStart = Math.max(runningCount + 2, shots.length - 2);
      updateNodeData(node.id, {
        videoBatchStatus: "generating",
        videoBatchProgress: 2,
        videoBatchRunningCount: runningCount,
        videoBatchFailedShotIds: shots
          .slice(failedStart)
          .map((shot) => shot.id),
      });
    },
    [updateNodeData],
  );

  return {
    handleCloseStoryboardComposer,
    handleStoryboardComposerSubmit,
    handleRunStoryboardImageGroup,
    handleToggleScriptShot,
    handleToggleAllScriptShots,
    handleSelectStoryboardStyle,
    handleSelectStoryboardShot,
    handleToggleStoryboardVideoShot,
    handleToggleAllStoryboardVideoShots,
    handleOpenStoryboardVideoDialog,
    handleCloseStoryboardVideoDialog,
    handleGenerateStoryboardVideos,
    handleRunStoryboardVideoGroup,
  };
}
