import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import type {
  DirectorStageCapture,
  DirectorStageModelAsset,
  DirectorStageObjectKind,
  DirectorStageProject,
} from "./directorStageTypes";
import type { Translate } from "../ImageNode/types";

export type DirectorStageCapturePayload = {
  dataUrl: string;
  fileName: string;
  project: DirectorStageProject;
};

export type DirectorStageCaptureResult =
  | {
      ok: true;
      capture?: DirectorStageCapture;
    }
  | {
      ok: false;
      error: string;
    };

export type DirectorStageCaptureBatchResult =
  | {
      ok: true;
      captures: DirectorStageCapture[];
    }
  | {
      ok: false;
      error: string;
    };

export type DirectorStageModelUploadResult =
  | {
      ok: true;
      model: DirectorStageModelAsset;
    }
  | {
      ok: false;
      error: string;
    };

export type DirectorStageWorkflow = {
  openNodeId: string | null;
  handleOpenStage: (node: AigcCanvasNode) => void;
  handleCloseStage: () => void;
  handleSaveProject: (
    node: AigcCanvasNode,
    project: DirectorStageProject,
  ) => void;
  handleCapture: (
    node: AigcCanvasNode,
    payload: DirectorStageCapturePayload,
  ) => Promise<DirectorStageCaptureResult>;
  handleCaptureBatch: (
    node: AigcCanvasNode,
    payloads: DirectorStageCapturePayload[],
  ) => Promise<DirectorStageCaptureBatchResult>;
  handleUploadModel: (
    node: AigcCanvasNode,
    file: File,
    kind: DirectorStageObjectKind,
  ) => Promise<DirectorStageModelUploadResult>;
};

export type DirectorStageNodeProps = {
  node: AigcCanvasNode;
  selected: boolean;
  sourcePreviewUrl?: string;
  t: Translate;
  workflow: DirectorStageWorkflow;
};

export type DirectorStageFullscreenProps = {
  node: AigcCanvasNode;
  sourcePreviewUrl?: string;
  t: Translate;
  workflow: DirectorStageWorkflow;
};

export type DirectorStageEditorProps = {
  initialProject: DirectorStageProject;
  captures: DirectorStageCapture[];
  sourcePreviewUrl?: string;
  onCapture: (
    payload: DirectorStageCapturePayload,
  ) => DirectorStageCaptureResult | Promise<DirectorStageCaptureResult>;
  onCaptureBatch: (
    payloads: DirectorStageCapturePayload[],
  ) =>
    | DirectorStageCaptureBatchResult
    | Promise<DirectorStageCaptureBatchResult>;
  onClose: () => void;
  onSave: (project: DirectorStageProject) => void;
  onUploadModel: (
    file: File,
    kind: DirectorStageObjectKind,
  ) => Promise<DirectorStageModelUploadResult>;
};
