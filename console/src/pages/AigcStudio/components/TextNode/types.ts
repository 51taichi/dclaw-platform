import type { ReactNode } from "react";
import type { useTranslation } from "react-i18next";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type TextTryAction =
  | "write"
  | "text_to_video"
  | "image_to_prompt"
  | "text_to_music";

export type TextFormatAction =
  | "clear"
  | "h1"
  | "h2"
  | "h3"
  | "paragraph"
  | "bold"
  | "italic"
  | "list"
  | "bullet"
  | "rule"
  | "duplicate"
  | "expand";

export type TextNodeProps = {
  node: AigcCanvasNode;
  selected: boolean;
  editingNodeId: string | null;
  textModelMenuNodeId: string | null;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions: AigcCapabilityInfo[];
  currentModelKey: string;
  nodeIcon: (type: string) => ReactNode;
  t: Translate;
  onFormat: (node: AigcCanvasNode, action: TextFormatAction) => void;
  onTry: (node: AigcCanvasNode, action: TextTryAction) => void;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onBeginGeneratedEdit: (nodeId: string) => void;
  onToggleModelMenu: (nodeId: string) => void;
  onSelectTextModel: (node: AigcCanvasNode, model: AigcCapabilityInfo) => void;
  onSubmitComposer: (node: AigcCanvasNode) => void | Promise<void>;
};
