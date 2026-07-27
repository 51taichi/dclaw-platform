import type { useTranslation } from "react-i18next";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import type { ImageReferenceAsset } from "../../canvasJobActions";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type VideoComposerMenu =
  | "model"
  | "settings"
  | "advanced"
  | "count"
  | "effect"
  | "motion"
  | "character";

export type VideoComposerMenuState = {
  nodeId: string;
  menu: VideoComposerMenu;
} | null;

export type VideoTryAction = "first_last_frames" | "first_frame";

export type VideoReferenceMode =
  | "all_reference"
  | "image_to_video"
  | "first_frame"
  | "image_reference";

export type VideoConnectedInputs = {
  imageCount: number;
  videoCount: number;
  audioCount: number;
  totalCount: number;
};

export type VideoResultAction =
  | "edit"
  | "crop"
  | "upscale"
  | "analyze"
  | "remove_subtitles"
  | "extract_audio";

export type VideoNodeWorkflow = {
  handleVideoUpload: (
    node: AigcCanvasNode,
    file?: File,
  ) => void | Promise<void>;
  handleVideoTryUpload: (
    node: AigcCanvasNode,
    action: VideoTryAction,
    files?: FileList | null,
  ) => void | Promise<void>;
  handleVideoReferenceUpload: (
    node: AigcCanvasNode,
    mode: VideoReferenceMode,
    files?: FileList | null,
  ) => void | Promise<void>;
  handleGeneratedVideoAction: (
    node: AigcCanvasNode,
    action: VideoResultAction,
  ) => void;
  handleVideoCancelGeneration: (node: AigcCanvasNode) => void;
  handleVideoRetryGeneration: (node: AigcCanvasNode) => void;
  handleVideoComposerSubmit: (node: AigcCanvasNode) => AigcCanvasNode;
};

export type VideoNodeProps = {
  node: AigcCanvasNode;
  selected: boolean;
  t: Translate;
  workflow: VideoNodeWorkflow;
};

export type VideoComposerProps = {
  node: AigcCanvasNode;
  videoComposerMenu: VideoComposerMenuState;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions: AigcCapabilityInfo[];
  currentModelKey: string;
  connectedInputs?: VideoConnectedInputs;
  referenceAssets?: ImageReferenceAsset[];
  t: Translate;
  workflow: VideoNodeWorkflow;
  disabled?: boolean;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onToggleMenu: (nodeId: string, menu: VideoComposerMenu) => void;
  onSelectModel: (model: AigcCapabilityInfo) => void;
  onCloseMenu: () => void;
};
