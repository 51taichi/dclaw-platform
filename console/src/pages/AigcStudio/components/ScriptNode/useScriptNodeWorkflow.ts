import { useCallback, type Dispatch, type SetStateAction } from "react";

import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import type {
  ScriptAssetGenerationOptions,
  ScriptNodeWorkflow,
  StoryboardWorkflow,
  Translate,
} from "./types";
import {
  SCRIPT_STORYBOARD_INPUT_PROMPT,
  scriptMode,
  scriptSelectedShotIds,
  type ScriptTryAction,
  type ScriptViewMode,
  type ScriptWorkflowStep,
} from "./scriptNodeState";

type UseScriptNodeWorkflowArgs = {
  activeCanvas: AigcCanvas | null;
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  setActiveCanvas: Dispatch<SetStateAction<AigcCanvas | null>>;
  setCanvases: Dispatch<SetStateAction<AigcCanvas[]>>;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  setAddMenuOpen: Dispatch<SetStateAction<boolean>>;
  setContextMenu: (value: null) => void;
  setCanvasContextMenu: (value: null) => void;
  setQuickTemplateMenu: (value: null) => void;
  setPortMenu: (value: null) => void;
  setTextModelMenuNodeId: Dispatch<SetStateAction<string | null>>;
  setImageComposerMenu: (value: null) => void;
  setVideoComposerMenu: (value: null) => void;
  connectCanvasNodes: (source: string, target: string) => AigcCanvasEdge;
  runScriptNode?: (
    node: AigcCanvasNode,
    canvas: AigcCanvas,
  ) => void | Promise<void>;
  runAssetImageNode?: (
    node: AigcCanvasNode,
    canvas: AigcCanvas,
  ) => void | Promise<void>;
  storyboardWorkflow: Pick<
    StoryboardWorkflow,
    "handleStoryboardComposerSubmit"
  >;
  t: Translate;
};

function scriptAssetStatesFromNode(node: AigcCanvasNode) {
  const states = node.data.scriptAssetStates;
  if (!states || typeof states !== "object" || Array.isArray(states)) {
    return {};
  }
  return states as Record<string, string>;
}

function scriptPromptStatesFromNode(node: AigcCanvasNode) {
  const states = node.data.scriptPromptStates;
  if (!states || typeof states !== "object" || Array.isArray(states)) {
    return {};
  }
  return states as Record<string, string>;
}

type ScriptGeneratedAssetKind = "character" | "scene" | "prop";

function scriptAssetKindFromId(assetId: string): ScriptGeneratedAssetKind {
  const [kind] = assetId.split(":");
  if (kind === "scene" || kind === "prop") return kind;
  return "character";
}

function scriptAssetLabelFromId(assetId: string) {
  const [, ...labelParts] = assetId.split(":");
  return labelParts.join(":") || assetId;
}

function scriptAssetNodeIdFromAssetId(node: AigcCanvasNode, assetId: string) {
  const safeAssetId = assetId
    .replace(/[:\s/\\]+/g, "-")
    .replace(/[^a-zA-Z0-9_\-\u4e00-\u9fa5]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `script-asset-${node.id}-${safeAssetId || "asset"}`;
}

const DEFAULT_SCRIPT_ASSET_IMAGE_PARAMETERS = {
  aspectRatio: "2:1",
  imageQuality: "标准画质",
  resolution: "2K",
};

function optionText(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function scriptAssetImageParametersFromOptions(
  options: ScriptAssetGenerationOptions = {},
) {
  const parameters: Record<string, string> = {
    ...DEFAULT_SCRIPT_ASSET_IMAGE_PARAMETERS,
  };
  const modelLabel = optionText(options.modelLabel);
  const providerId = optionText(options.providerId);
  const providerName = optionText(options.providerName);
  const modelId = optionText(options.modelId);
  const modelCapability = optionText(options.modelCapability);
  const imageQuality = optionText(options.imageQuality);
  const resolution = optionText(options.resolution);
  const aspectRatio = optionText(options.aspectRatio);

  if (modelLabel) parameters.modelLabel = modelLabel;
  if (providerId) parameters.providerId = providerId;
  if (providerName) parameters.providerName = providerName;
  if (modelId) parameters.modelId = modelId;
  if (modelCapability) parameters.modelCapability = modelCapability;
  if (imageQuality) parameters.imageQuality = imageQuality;
  if (resolution) parameters.resolution = resolution;
  if (aspectRatio) parameters.aspectRatio = aspectRatio;

  return parameters;
}

function scriptAssetPrompt(kind: ScriptGeneratedAssetKind, label: string) {
  if (kind === "scene") {
    return `${label}，场景资产图，电影感环境设定，清晰空间结构，作为短剧分镜的场景设定资产`;
  }
  if (kind === "prop") {
    return `${label}，道具资产图，单体清晰，材质细节明确，作为短剧分镜的道具设定资产`;
  }
  return `${label}，角色资产图，正面设定照，服装发型清晰，电影感，作为短剧分镜的角色设定资产`;
}

export function useScriptNodeWorkflow({
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
  runScriptNode,
  runAssetImageNode,
  storyboardWorkflow,
  t,
}: UseScriptNodeWorkflowArgs): ScriptNodeWorkflow {
  const closeScriptMenus = useCallback(() => {
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

  const handleScriptTry = useCallback(
    (node: AigcCanvasNode, action: ScriptTryAction) => {
      if (action === "script") {
        const storyboardPrompt = t(
          "aigcStudio.scriptNode.storyboardInputPrompt",
          SCRIPT_STORYBOARD_INPUT_PROMPT,
        );
        updateNodeData(node.id, {
          scriptInputKind: "script",
          scriptPrompt: storyboardPrompt,
          composerPlaceholder: t(
            "aigcStudio.scriptNode.composerPlaceholder",
            "描述剧情片段、故事，为你生成分镜脚本",
          ),
          composerText: "",
          scriptMode: "idle",
          scriptView: "script",
          scriptWorkflowStep: "shots",
          scriptSourceNodeId: null,
        });
        setSelectedNodeId(node.id);
        setAddMenuOpen(false);
        setContextMenu(null);
        setCanvasContextMenu(null);
        setQuickTemplateMenu(null);
        setPortMenu(null);
        return;
      }

      const prompt =
        action === "video"
          ? t("aigcStudio.scriptNode.prompts.video", "根据视频参考生成分镜脚本")
          : action === "character"
          ? t(
              "aigcStudio.scriptNode.prompts.character",
              "根据角色参考生成分镜脚本",
            )
          : action === "write"
          ? t("aigcStudio.scriptNode.prompts.write", "自己编写分镜脚本")
          : t(
              "aigcStudio.scriptNode.defaultPrompt",
              "根据我上传的脚本生成一个完整的故事脚本",
            );
      updateNodeData(node.id, {
        scriptInputKind: action,
        scriptPrompt: prompt,
        scriptMode: "idle",
        scriptView: "script",
        scriptWorkflowStep: "shots",
      });
    },
    [
      setAddMenuOpen,
      setCanvasContextMenu,
      setContextMenu,
      setPortMenu,
      setQuickTemplateMenu,
      setSelectedNodeId,
      t,
      updateNodeData,
    ],
  );

  const submitScriptRun = useCallback(
    (node: AigcCanvasNode) => {
      if (!activeCanvas) return;
      const targetNode =
        activeCanvas.nodes.find((item) => item.id === node.id) ?? node;
      const nodeSnapshot: AigcCanvasNode = {
        ...targetNode,
        data: {
          ...targetNode.data,
          ...node.data,
          scriptMode: "generating_script",
          scriptProgress: 4,
          scriptView: "script",
          scriptWorkflowStep: "shots",
          scriptParseStatus: null,
          scriptParseError: null,
          scriptRawOutput: null,
          selectedStoryboardShotId: null,
          selectedStoryboardVideoShotIds: [],
          storyboardImageShotIds: [],
          scriptShots: [],
          selectedShotIds: [],
          job_error: null,
          outputs: [],
        },
      };
      const updatedCanvas: AigcCanvas = {
        ...activeCanvas,
        nodes: activeCanvas.nodes.map((item) =>
          item.id === node.id ? nodeSnapshot : item,
        ),
      };
      void runScriptNode?.(nodeSnapshot, updatedCanvas);
    },
    [activeCanvas, runScriptNode],
  );

  const handleScriptComposerSubmit = useCallback(
    (node: AigcCanvasNode) => {
      const mode = scriptMode(node);
      if (mode === "storyboard_select") {
        storyboardWorkflow.handleStoryboardComposerSubmit(node);
        return;
      }
      submitScriptRun(node);
    },
    [storyboardWorkflow, submitScriptRun],
  );

  const handleScriptRegenerate = useCallback(
    (node: AigcCanvasNode) => {
      submitScriptRun(node);
    },
    [submitScriptRun],
  );

  const handleScriptViewChange = useCallback(
    (node: AigcCanvasNode, view: ScriptViewMode) => {
      updateNodeData(node.id, { scriptView: view });
    },
    [updateNodeData],
  );

  const handleScriptGenerateStoryboard = useCallback(
    (node: AigcCanvasNode) => {
      updateNodeData(node.id, {
        scriptMode: "script_ready",
        scriptView: "script",
        scriptWorkflowStep: "prompts",
        selectedShotIds: scriptSelectedShotIds(node),
        storyboardBatchDialogOpen: true,
        storyboardStyle: node.data.storyboardStyle ?? "Lib Image",
        storyboardStyleMenuOpen: false,
      });
      setSelectedNodeId(node.id);
      closeScriptMenus();
    },
    [closeScriptMenus, setSelectedNodeId, updateNodeData],
  );

  const handleScriptWorkflowStepChange = useCallback(
    (node: AigcCanvasNode, step: ScriptWorkflowStep) => {
      updateNodeData(node.id, { scriptWorkflowStep: step });
    },
    [updateNodeData],
  );

  const handleScriptAssetSelect = useCallback(
    (node: AigcCanvasNode, assetId: string) => {
      updateNodeData(node.id, { selectedScriptAssetId: assetId });
    },
    [updateNodeData],
  );

  const handleScriptAssetGenerate = useCallback(
    (node: AigcCanvasNode, assetId: string) => {
      const currentStates = scriptAssetStatesFromNode(node);
      updateNodeData(node.id, {
        selectedScriptAssetId: assetId,
        scriptAssetStates: {
          ...currentStates,
          [assetId]: "generating",
        },
        scriptAssetProgress: 4,
      });
      if (activeCanvas) {
        const assetNodeId = scriptAssetNodeIdFromAssetId(node, assetId);
        const targetNode =
          activeCanvas.nodes.find((item) => item.id === node.id) ?? node;
        const kind = scriptAssetKindFromId(assetId);
        const label = scriptAssetLabelFromId(assetId);
        const existingNode = activeCanvas.nodes.find(
          (item) => item.id === assetNodeId,
        );
        const assetNode: AigcCanvasNode = {
          id: assetNodeId,
          type: "image_generate",
          position: existingNode?.position ?? {
            x: targetNode.position.x - 470,
            y: targetNode.position.y,
          },
          data: {
            ...(existingNode?.data ?? {}),
            title: t(
              "aigcStudio.scriptNode.assetImageTitle",
              "资产图 · {{label}}",
              {
                label,
              },
            ),
            text: scriptAssetPrompt(kind, label),
            composerText: scriptAssetPrompt(kind, label),
            imageMode: "text_to_image",
            job_error: null,
            ...(runAssetImageNode
              ? {
                  imageState: "generating",
                  imageProgress: 2,
                  job_status: "queued",
                  outputs: [],
                }
              : {}),
            sourceScriptNodeId: targetNode.id,
            scriptAssetId: assetId,
            scriptAssetKind: kind,
            scriptAssetLabel: label,
            aspectRatio: "1:1",
            resolution: "2K",
            imageCount: 1,
            inputUpdated: true,
          },
        };
        const hasEdge = activeCanvas.edges.some(
          (edge) =>
            edge.source === targetNode.id && edge.target === assetNodeId,
        );
        const updated: AigcCanvas = {
          ...activeCanvas,
          nodes: activeCanvas.nodes
            .map((item) =>
              item.id === targetNode.id
                ? {
                    ...item,
                    data: {
                      ...item.data,
                      selectedScriptAssetId: assetId,
                      scriptAssetNodeIds: Array.from(
                        new Set([
                          ...(Array.isArray(item.data.scriptAssetNodeIds)
                            ? item.data.scriptAssetNodeIds.map(String)
                            : []),
                          assetNodeId,
                        ]),
                      ),
                      scriptAssetStates: {
                        ...scriptAssetStatesFromNode(item),
                        [assetId]: "generating",
                      },
                      scriptAssetProgress: null,
                    },
                  }
                : item.id === assetNodeId
                ? assetNode
                : item,
            )
            .concat(existingNode ? [] : [assetNode]),
          edges: hasEdge
            ? activeCanvas.edges
            : [
                ...activeCanvas.edges,
                connectCanvasNodes(targetNode.id, assetNodeId),
              ],
        };
        setActiveCanvas(updated);
        setCanvases((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
        setSelectedNodeId(assetNodeId);
        void runAssetImageNode?.(assetNode, updated);
        return;
      }
      window.setTimeout(() => {
        updateNodeData(node.id, {
          selectedScriptAssetId: assetId,
          scriptAssetStates: {
            ...currentStates,
            [assetId]: "ready",
          },
          scriptAssetProgress: 100,
        });
      }, 260);
    },
    [
      activeCanvas,
      connectCanvasNodes,
      runAssetImageNode,
      setActiveCanvas,
      setCanvases,
      setSelectedNodeId,
      t,
      updateNodeData,
    ],
  );

  const handleScriptAssetsGenerateAll = useCallback(
    (
      node: AigcCanvasNode,
      assetIds: string[],
      options?: ScriptAssetGenerationOptions,
    ) => {
      const currentStates = scriptAssetStatesFromNode(node);
      const imageParameters = scriptAssetImageParametersFromOptions(options);
      const generatingStates = assetIds.reduce<Record<string, string>>(
        (states, assetId) => ({
          ...states,
          [assetId]: "generating",
        }),
        currentStates,
      );
      updateNodeData(node.id, {
        scriptAssetStates: generatingStates,
        scriptAssetProgress: 4,
      });
      if (activeCanvas) {
        const firstAssetNodeId = assetIds[0]
          ? scriptAssetNodeIdFromAssetId(node, assetIds[0])
          : node.id;
        const targetNode =
          activeCanvas.nodes.find((item) => item.id === node.id) ?? node;
        const existingNodeIds = new Set(
          activeCanvas.nodes.map((item) => item.id),
        );
        const assetNodes = assetIds.map((assetId, index) => {
          const kind = scriptAssetKindFromId(assetId);
          const label = scriptAssetLabelFromId(assetId);
          const nodeId = scriptAssetNodeIdFromAssetId(targetNode, assetId);
          const existingNode = activeCanvas.nodes.find(
            (item) => item.id === nodeId,
          );
          return {
            id: nodeId,
            type: "image_generate",
            position: existingNode?.position ?? {
              x: targetNode.position.x - 470,
              y: targetNode.position.y + index * 220,
            },
            data: {
              ...(existingNode?.data ?? {}),
              title: t(
                "aigcStudio.scriptNode.assetImageTitle",
                "资产图 · {{label}}",
                { label },
              ),
              text: scriptAssetPrompt(kind, label),
              composerText: scriptAssetPrompt(kind, label),
              imageMode: "text_to_image",
              job_error: null,
              ...(runAssetImageNode
                ? {
                    imageState: "generating",
                    imageProgress: 2,
                    job_status: "queued",
                    outputs: [],
                  }
                : {}),
              sourceScriptNodeId: targetNode.id,
              scriptAssetId: assetId,
              scriptAssetKind: kind,
              scriptAssetLabel: label,
              ...imageParameters,
              imageCount: 1,
              inputUpdated: true,
            },
          } as AigcCanvasNode;
        });
        const assetNodeIds = assetNodes.map((item) => item.id);
        const assetNodeById = new Map(
          assetNodes.map((item) => [item.id, item]),
        );
        const existingEdgeKeys = new Set(
          activeCanvas.edges.map((edge) => `${edge.source}:${edge.target}`),
        );
        const newEdges = assetNodes
          .filter(
            (item) => !existingEdgeKeys.has(`${targetNode.id}:${item.id}`),
          )
          .map((item) => connectCanvasNodes(targetNode.id, item.id));
        const updated: AigcCanvas = {
          ...activeCanvas,
          nodes: activeCanvas.nodes
            .map((item) => {
              if (item.id === targetNode.id) {
                return {
                  ...item,
                  data: {
                    ...item.data,
                    scriptAssetNodeIds: assetNodeIds,
                    scriptAssetStates: generatingStates,
                    scriptAssetProgress: null,
                  },
                };
              }
              return assetNodeById.get(item.id) ?? item;
            })
            .concat(assetNodes.filter((item) => !existingNodeIds.has(item.id))),
          edges: [...activeCanvas.edges, ...newEdges],
        };
        setActiveCanvas(updated);
        setCanvases((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
        setSelectedNodeId(firstAssetNodeId);
        assetNodes.forEach((assetNode) => {
          void runAssetImageNode?.(assetNode, updated);
        });
        return;
      }
      window.setTimeout(() => {
        updateNodeData(node.id, {
          scriptAssetStates: assetIds.reduce<Record<string, string>>(
            (states, assetId) => ({
              ...states,
              [assetId]: "ready",
            }),
            currentStates,
          ),
          scriptAssetProgress: 100,
        });
      }, 260);
    },
    [
      activeCanvas,
      connectCanvasNodes,
      runAssetImageNode,
      setActiveCanvas,
      setCanvases,
      setSelectedNodeId,
      t,
      updateNodeData,
    ],
  );

  const handleScriptPromptSelect = useCallback(
    (node: AigcCanvasNode, shotId: string) => {
      updateNodeData(node.id, { selectedScriptPromptShotId: shotId });
    },
    [updateNodeData],
  );

  const handleScriptPromptGenerate = useCallback(
    (node: AigcCanvasNode, shotId: string) => {
      const currentStates = scriptPromptStatesFromNode(node);
      updateNodeData(node.id, {
        selectedScriptPromptShotId: shotId,
        scriptPromptStates: {
          ...currentStates,
          [shotId]: "generating",
        },
        scriptPromptProgress: 3,
      });
      window.setTimeout(() => {
        updateNodeData(node.id, {
          selectedScriptPromptShotId: shotId,
          scriptPromptStates: {
            ...currentStates,
            [shotId]: "ready",
          },
          scriptPromptProgress: 100,
        });
      }, 260);
    },
    [updateNodeData],
  );

  const handleScriptPromptsGenerateAll = useCallback(
    (node: AigcCanvasNode, shotIds: string[]) => {
      const currentStates = scriptPromptStatesFromNode(node);
      updateNodeData(node.id, {
        scriptPromptStates: shotIds.reduce<Record<string, string>>(
          (states, shotId) => ({
            ...states,
            [shotId]: "generating",
          }),
          currentStates,
        ),
        scriptPromptProgress: 3,
      });
      window.setTimeout(() => {
        updateNodeData(node.id, {
          scriptPromptStates: shotIds.reduce<Record<string, string>>(
            (states, shotId) => ({
              ...states,
              [shotId]: "ready",
            }),
            currentStates,
          ),
          scriptPromptProgress: 100,
        });
      }, 260);
    },
    [updateNodeData],
  );

  const handleToggleScriptFullscreen = useCallback(
    (node: AigcCanvasNode) => {
      updateNodeData(node.id, {
        scriptFullscreen: node.data.scriptFullscreen !== true,
      });
    },
    [updateNodeData],
  );

  return {
    handleScriptTry,
    handleScriptComposerSubmit,
    handleScriptRegenerate,
    handleScriptViewChange,
    handleScriptGenerateStoryboard,
    handleScriptWorkflowStepChange,
    handleScriptAssetSelect,
    handleScriptAssetGenerate,
    handleScriptAssetsGenerateAll,
    handleScriptPromptSelect,
    handleScriptPromptGenerate,
    handleScriptPromptsGenerateAll,
    handleToggleScriptFullscreen,
  };
}
