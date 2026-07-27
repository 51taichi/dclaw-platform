import type { Dispatch, SetStateAction } from "react";
import type { ReactNode } from "react";
import type { useTranslation } from "react-i18next";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type UploadedAssetNodeProps = {
  node: AigcCanvasNode;
  t: Translate;
  onReplace: (node: AigcCanvasNode, file?: File) => void | Promise<void>;
  onUpdateNodeData?: (nodeId: string, data: Record<string, unknown>) => void;
};

export type ReferenceNoteNodeProps = {
  node: AigcCanvasNode;
  icon: ReactNode;
  t: Translate;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
};
