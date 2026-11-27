import type { useTranslation } from "react-i18next";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import type {
  ScriptShot,
  ScriptTryAction,
  ScriptViewMode,
  ScriptWorkflowStep,
} from "./scriptNodeState";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type ScriptAssetGenerationOptions = {
  modelLabel?: string;
  providerId?: string;
  providerName?: string;
  modelId?: string;
  modelCapability?: string;
  imageQuality?: string;
  resolution?: string;
  aspectRatio?: string;
};

export type ScriptNodeWorkflow = {
  handleScriptTry: (node: AigcCanvasNode, action: ScriptTryAction) => void;
  handleScriptComposerSubmit: (node: AigcCanvasNode) => void;
  handleScriptRegenerate: (node: AigcCanvasNode) => void;
  handleScriptViewChange: (node: AigcCanvasNode, view: ScriptViewMode) => void;
  handleScriptGenerateStoryboard: (node: AigcCanvasNode) => void;
  handleScriptWorkflowStepChange: (
    node: AigcCanvasNode,
    step: ScriptWorkflowStep,
  ) => void;
  handleScriptAssetSelect: (node: AigcCanvasNode, assetId: string) => void;
  handleScriptAssetGenerate: (node: AigcCanvasNode, assetId: string) => void;
  handleScriptAssetsGenerateAll: (
    node: AigcCanvasNode,
    assetIds: string[],
    options?: ScriptAssetGenerationOptions,
  ) => void;
  handleScriptPromptSelect: (node: AigcCanvasNode, shotId: string) => void;
  handleScriptPromptGenerate: (node: AigcCanvasNode, shotId: string) => void;
  handleScriptPromptsGenerateAll: (
    node: AigcCanvasNode,
    shotIds: string[],
  ) => void;
  handleToggleScriptFullscreen: (node: AigcCanvasNode) => void;
};

export type StoryboardWorkflow = {
  handleCloseStoryboardComposer: (node: AigcCanvasNode) => void;
  handleStoryboardComposerSubmit: (node: AigcCanvasNode) => void;
  handleRunStoryboardImageGroup: (node: AigcCanvasNode) => void;
  handleToggleScriptShot: (
    node: AigcCanvasNode,
    shotId: string,
    checked: boolean,
  ) => void;
  handleToggleAllScriptShots: (node: AigcCanvasNode, checked: boolean) => void;
  handleSelectStoryboardStyle: (
    node: AigcCanvasNode,
    styleName: string,
  ) => void;
  handleSelectStoryboardShot: (node: AigcCanvasNode, shot: ScriptShot) => void;
  handleToggleStoryboardVideoShot: (
    node: AigcCanvasNode,
    shotId: string,
    checked: boolean,
  ) => void;
  handleToggleAllStoryboardVideoShots: (
    node: AigcCanvasNode,
    checked: boolean,
  ) => void;
  handleOpenStoryboardVideoDialog: (node: AigcCanvasNode) => void;
  handleCloseStoryboardVideoDialog: (node: AigcCanvasNode) => void;
  handleGenerateStoryboardVideos: (node: AigcCanvasNode) => void;
  handleRunStoryboardVideoGroup: (node: AigcCanvasNode) => void;
};

export type ScriptNodeProps = {
  node: AigcCanvasNode;
  selected: boolean;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions?: AigcCapabilityInfo[];
  t: Translate;
  scriptWorkflow: ScriptNodeWorkflow;
  storyboardWorkflow: StoryboardWorkflow;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
};
