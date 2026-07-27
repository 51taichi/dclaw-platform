import type { useTranslation } from "react-i18next";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import type { ImageReferenceAsset } from "../../canvasJobActions";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type ImageComposerMenu =
  | "model"
  | "size"
  | "camera"
  | "advanced"
  | "count";

export type ImageComposerMenuState = {
  nodeId: string;
  menu: ImageComposerMenu;
} | null;

export type ImageSlashCommand = {
  title: string;
  description: string;
};

export type ImageCaptureMode = "current" | "four" | "twelve";

export type ImageNodeWorkflow = {
  handleImageUpload: (
    node: AigcCanvasNode,
    file?: File,
  ) => void | Promise<void>;
  handleImageToImageUpload: (
    node: AigcCanvasNode,
    file?: File,
  ) => void | Promise<void>;
  handleImageUpscaleUpload: (
    node: AigcCanvasNode,
    file?: File,
  ) => void | Promise<void>;
  handleImageComposerSubmit: (node: AigcCanvasNode) => AigcCanvasNode;
  handleImageCaptureGroup: (
    node: AigcCanvasNode,
    mode: ImageCaptureMode,
  ) => void;
  handleGeneratedImageSendToImage: (node: AigcCanvasNode) => void;
  handleGeneratedImageAnnotate: (node: AigcCanvasNode) => void;
  handleGeneratedImageSetPrimary: (
    node: AigcCanvasNode,
    outputId: string,
  ) => void;
  handleGeneratedImageToggleResults: (
    node: AigcCanvasNode,
    expanded: boolean,
  ) => void;
  handleImageCaptureGroupSendToImage: (node: AigcCanvasNode) => void;
  handleImageCaptureGroupSelect: (
    node: AigcCanvasNode,
    captureId: string,
  ) => void;
  handleImageSlashCommand: (
    node: AigcCanvasNode,
    command: ImageSlashCommand,
  ) => void;
};

export type ImageNodeProps = {
  node: AigcCanvasNode;
  selected: boolean;
  t: Translate;
  workflow: ImageNodeWorkflow;
};

export type ImageCaptureGroupNodeProps = {
  node: AigcCanvasNode;
  t: Translate;
  workflow: ImageNodeWorkflow;
};

export type ImageComposerProps = {
  node: AigcCanvasNode;
  imageComposerMenu: ImageComposerMenuState;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions: AigcCapabilityInfo[];
  currentModelKey: string;
  referenceAssets?: ImageReferenceAsset[];
  t: Translate;
  workflow: ImageNodeWorkflow;
  disabled: boolean;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onRunNode: (node: AigcCanvasNode) => void;
  onToggleMenu: (nodeId: string, menu: ImageComposerMenu) => void;
  onSelectModel: (model: AigcCapabilityInfo) => void;
  onCloseMenu: () => void;
};
