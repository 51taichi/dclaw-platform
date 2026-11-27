import { lazy, Suspense } from "react";
import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";

import styles from "../../index.module.less";
import {
  createDefaultDirectorStageProject,
  directorStageCapturesFromNode,
  directorStageProjectFromNode,
} from "./directorStageTypes";
import type { DirectorStageFullscreenProps } from "./types";

const DirectorStageEditor = lazy(() => import("./DirectorStageEditor"));

export function DirectorStageFullscreen({
  node,
  sourcePreviewUrl,
  t,
  workflow,
}: DirectorStageFullscreenProps) {
  const project =
    directorStageProjectFromNode(node) ??
    createDefaultDirectorStageProject(sourcePreviewUrl);

  const content = (
    <div
      className={styles.directorStageFullscreen}
      role="dialog"
      aria-label={t("aigcStudio.directorStage.fullscreen", "3D导演台")}
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
    >
      <div className={styles.directorStageFullscreenHeader}>
        <div>
          <strong>
            {t("aigcStudio.directorStage.fullscreen", "3D导演台")}
          </strong>
          <span>{String(node.data.title ?? "Director Stage")}</span>
        </div>
        <button
          type="button"
          aria-label={t("aigcStudio.close", "关闭")}
          onClick={workflow.handleCloseStage}
        >
          <X size={18} />
        </button>
      </div>
      <Suspense
        fallback={
          <div className={styles.directorStageLoading}>
            <Loader2 size={20} />
            {t("aigcStudio.directorStage.loading", "正在加载 3D 导演台")}
          </div>
        }
      >
        <DirectorStageEditor
          captures={directorStageCapturesFromNode(node)}
          initialProject={project}
          sourcePreviewUrl={sourcePreviewUrl}
          onClose={workflow.handleCloseStage}
          onSave={(project) => workflow.handleSaveProject(node, project)}
          onCapture={(payload) => workflow.handleCapture(node, payload)}
          onCaptureBatch={(payloads) =>
            workflow.handleCaptureBatch(node, payloads)
          }
          onUploadModel={(file, kind) =>
            workflow.handleUploadModel(node, file, kind)
          }
        />
      </Suspense>
    </div>
  );

  return typeof document === "undefined"
    ? content
    : createPortal(content, document.body);
}
