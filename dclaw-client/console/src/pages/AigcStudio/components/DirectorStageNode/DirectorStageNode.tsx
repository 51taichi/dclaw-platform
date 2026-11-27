import { Camera, Cuboid, Maximize2, UserRound } from "lucide-react";

import styles from "../../index.module.less";
import {
  directorStageCapturesFromNode,
  directorStageStats,
} from "./directorStageTypes";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import { DirectorStageFullscreen } from "./DirectorStageFullscreen";
import type { DirectorStageNodeProps } from "./types";

const formatTemplate = (
  template: string,
  values: Record<string, string | number>,
) =>
  Object.entries(values).reduce(
    (text, [key, value]) => text.split(`{{${key}}}`).join(String(value)),
    template,
  );

export function DirectorStageNode({
  node,
  sourcePreviewUrl,
  t,
  workflow,
}: DirectorStageNodeProps) {
  const stats = directorStageStats(node);
  const captures = directorStageCapturesFromNode(node);
  const latestCapture = captures[captures.length - 1];
  const stateLabel = stats.project
    ? t("aigcStudio.directorStage.saved", "已保存场景")
    : t("aigcStudio.directorStage.empty", "未创建场景");
  const summary = formatTemplate(
    t(
      "aigcStudio.directorStage.summary",
      "角色 {{characters}} · 道具 {{props}} · 机位 {{cameras}}",
      {
        characters: stats.characterCount,
        props: stats.propCount,
        cameras: stats.cameraCount,
      },
    ),
    {
      cameras: stats.cameraCount,
      characters: stats.characterCount,
      props: stats.propCount,
    },
  );
  const captureLabel = formatTemplate(
    t(
      "aigcStudio.directorStage.captureCount",
      "截图 {{count}} 张",
      { count: stats.captureCount },
    ),
    { count: stats.captureCount },
  );

  return (
    <>
      <div className={styles.directorStageCard}>
        <div className={styles.nodeLabel}>
          <span>
            <Cuboid size={15} />
            {String(node.data.title ?? t("aigcStudio.nodeType.director_stage", "导演台"))}
          </span>
          <span className={styles.nodeTypeBadge}>
            {t("aigcStudio.nodeType.director_stage", "导演台")}
          </span>
        </div>
        <div className={styles.directorStagePreview}>
          {latestCapture?.previewUrl ? (
            <AuthenticatedAssetImage
              alt={latestCapture.name}
              className={styles.directorStageCapturePreview}
              src={latestCapture.previewUrl}
            />
          ) : sourcePreviewUrl ? (
            <AuthenticatedAssetImage
              alt={t("aigcStudio.directorStage.sourcePreview", "导演台参考图")}
              className={styles.directorStageCapturePreview}
              src={sourcePreviewUrl}
            />
          ) : (
            <div className={styles.directorStageEmptyPreview}>
              <UserRound size={28} />
              <Camera size={28} />
            </div>
          )}
        </div>
        <div className={styles.directorStageMeta}>
          <strong>{stateLabel}</strong>
          <span>{summary}</span>
          <span>{captureLabel}</span>
          {String(node.data.directorStageError ?? "") ? (
            <small>{String(node.data.directorStageError)}</small>
          ) : null}
        </div>
        <button
          type="button"
          className={styles.directorStageOpenButton}
          onClick={(event) => {
            event.stopPropagation();
            workflow.handleOpenStage(node);
          }}
        >
          <Maximize2 size={14} />
          {t("aigcStudio.openStage", "打开导演台")}
        </button>
      </div>
      {workflow.openNodeId === node.id ? (
        <DirectorStageFullscreen
          node={node}
          sourcePreviewUrl={sourcePreviewUrl}
          t={t}
          workflow={workflow}
        />
      ) : null}
    </>
  );
}
