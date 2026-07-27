import type { MouseEvent as ReactMouseEvent } from "react";
import type { useTranslation } from "react-i18next";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type AudioNodeWorkflow = {
  handleAudioComposerSubmit: (node: AigcCanvasNode) => AigcCanvasNode;
};

export type AudioNodeProps = {
  node: AigcCanvasNode;
  t: Translate;
  onUpdateNodeData?: (nodeId: string, data: Record<string, unknown>) => void;
};

export type AudioComposerProps = {
  node: AigcCanvasNode;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions: AigcCapabilityInfo[];
  t: Translate;
  workflow: AudioNodeWorkflow;
  disabled: boolean;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onRunNode: (
    event?: ReactMouseEvent<HTMLButtonElement>,
    nodeSnapshot?: AigcCanvasNode,
  ) => void;
};
