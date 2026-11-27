import type { ReactNode } from "react";
import type { useTranslation } from "react-i18next";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";

export type Translate = ReturnType<typeof useTranslation>["t"];

export type GenericNodeProps = {
  node: AigcCanvasNode;
  icon: ReactNode;
  translatedType: string;
  t: Translate;
};

export type NodePreviewBlocksProps = {
  node: AigcCanvasNode;
  t: Translate;
};
