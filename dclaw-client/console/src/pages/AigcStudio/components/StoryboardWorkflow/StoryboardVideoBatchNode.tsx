import {
  AlertTriangle,
  Download,
  Film,
  Grid2X2,
  Play,
  Square,
} from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import { SCRIPT_SHOTS, type ScriptShot } from "../ScriptNode/scriptNodeState";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";

type StoryboardVideoBatchNodeProps = {
  node: AigcCanvasNode;
  selected?: boolean;
  t: Translate;
  storyboardWorkflow: StoryboardWorkflow;
};

export function StoryboardVideoBatchNode({
  node,
  selected = false,
  t,
  storyboardWorkflow,
}: StoryboardVideoBatchNodeProps) {
  const shots = Array.isArray(node.data.videoBatchShots)
    ? (node.data.videoBatchShots as ScriptShot[])
    : SCRIPT_SHOTS.slice(0, 12);
  const status =
    node.data.videoBatchStatus === "generating" ? "generating" : "idle";
  const progress = Number(node.data.videoBatchProgress ?? 2);
  const runningCount = Math.min(
    Number(node.data.videoBatchRunningCount ?? 0),
    shots.length,
  );
  const failedIds = new Set(
    Array.isArray(node.data.videoBatchFailedShotIds)
      ? node.data.videoBatchFailedShotIds.map(String)
      : [],
  );
  const showToolbar = selected || status === "generating";

  return (
    <>
      {showToolbar && (
        <div
          className={styles.storyboardGroupToolbar}
          onClick={(event) => event.stopPropagation()}
        >
          <span className={styles.storyboardGroupStatusDot} aria-hidden />
          <button type="button" aria-label="视频组">
            <Grid2X2 size={16} />
          </button>
          {status === "generating" ? (
            <button type="button" className={styles.storyboardGroupStop}>
              <Square size={15} />
              {t(
                "aigcStudio.scriptNode.stopVideoGroup",
                "停止 ({{running}}/{{count}})",
                {
                  running: runningCount,
                  count: shots.length,
                },
              )}
            </button>
          ) : (
            <button
              type="button"
              className={styles.storyboardGroupRun}
              onClick={() =>
                storyboardWorkflow.handleRunStoryboardVideoGroup(node)
              }
            >
              <Play size={15} />
              {t("aigcStudio.scriptNode.runStoryboardGroup", "整组执行")}
            </button>
          )}
          <button type="button">
            <Grid2X2 size={15} />
            {t("aigcStudio.scriptNode.ungroup", "解组")}
          </button>
          <button type="button">
            <Download size={15} />
            {t("aigcStudio.scriptNode.batchDownload", "批量下载")}
          </button>
        </div>
      )}
      <div className={styles.videoNodeLabel}>
        <span>
          <Film size={15} />
          {String(
            node.data.title ??
              t(
                "aigcStudio.scriptNode.videoBatchTitle",
                "视频组 - 分镜图 - 脚本生成器",
              ),
          )}
        </span>
      </div>
      <div
        className={styles.storyboardVideoBatchPanel}
        data-testid="aigc-storyboard-video-batch"
      >
        <div className={styles.storyboardGridHeader}>
          <strong>
            {t(
              "aigcStudio.scriptNode.videoBatchTitle",
              "视频组 - 分镜图 - 脚本生成器",
            )}
          </strong>
          <span>
            {t("aigcStudio.scriptNode.videoBatchCount", "{{count}} 个视频", {
              count: shots.length,
            })}
          </span>
        </div>
        <div className={styles.storyboardVideoGrid}>
          {shots.map((shot, index) => {
            const failed = status === "generating" && failedIds.has(shot.id);
            const running =
              status === "generating" && !failed && index < runningCount;
            const waiting = status === "generating" && !failed && !running;
            return (
              <div
                className={[
                  styles.storyboardVideoCard,
                  status === "idle" ? styles.storyboardVideoCardIdle : "",
                  running ? styles.storyboardVideoCardRunning : "",
                  waiting ? styles.storyboardVideoCardWaiting : "",
                  failed ? styles.storyboardVideoCardFailed : "",
                ].join(" ")}
                key={shot.id}
              >
                <span className={styles.storyboardVideoCardTitle}>
                  {t("aigcStudio.scriptNode.videoClipName", "分镜视频-{{no}}", {
                    no: shot.no,
                  })}
                </span>
                {status === "idle" && (
                  <span className={styles.storyboardVideoPlay} aria-hidden>
                    <Play size={36} />
                  </span>
                )}
                {running && (
                  <span className={styles.storyboardProgressBadge}>
                    {t(
                      "aigcStudio.scriptNode.generatingPercent",
                      "生成中 {{progress}}%...",
                      { progress },
                    )}
                    <button type="button">{t("common.cancel", "取消")}</button>
                  </span>
                )}
                {waiting && (
                  <span className={styles.storyboardVideoStatusTag}>
                    {t("aigcStudio.scriptNode.waiting", "等待中")}
                  </span>
                )}
                {failed && (
                  <span className={styles.storyboardVideoFailure}>
                    <AlertTriangle size={24} />
                    <strong>
                      {t("aigcStudio.scriptNode.generateFailed", "生成失败")}
                    </strong>
                    <em>
                      {t("aigcStudio.scriptNode.powerShortage", "算力不足")}
                    </em>
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
