import { Check, ChevronDown, Film, Loader2, Monitor, X } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import {
  scriptSelectedStoryboardVideoShotIds,
  scriptShotsFromNode,
} from "../ScriptNode/scriptNodeState";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";

type StoryboardVideoBatchDialogProps = {
  node: AigcCanvasNode;
  t: Translate;
  storyboardWorkflow: StoryboardWorkflow;
};

function videoDurationForShot(node: AigcCanvasNode, shotId: string) {
  const durations = node.data.storyboardVideoDurations;
  if (durations && typeof durations === "object" && !Array.isArray(durations)) {
    const duration = Number((durations as Record<string, unknown>)[shotId]);
    if (Number.isFinite(duration) && duration > 0) return duration;
  }
  const fallback = Number(node.data.storyboardVideoDuration ?? 5);
  return Number.isFinite(fallback) && fallback > 0 ? fallback : 5;
}

export function StoryboardVideoBatchDialog({
  node,
  t,
  storyboardWorkflow,
}: StoryboardVideoBatchDialogProps) {
  const shots = scriptShotsFromNode(node);
  const selectedIds = new Set(scriptSelectedStoryboardVideoShotIds(node));
  const selectedCount = selectedIds.size;
  const allSelected = shots.length > 0 && selectedCount === shots.length;
  const pending = node.data.storyboardVideoDialogPending === true;

  return (
    <div
      className={styles.storyboardBatchDialogOverlay}
      onClick={(event) => event.stopPropagation()}
    >
      <section
        role="dialog"
        aria-label={t("aigcStudio.scriptNode.batchVideo", "批量生视频")}
        className={styles.storyboardBatchDialog}
      >
        <header className={styles.storyboardBatchHeader}>
          <h3>{t("aigcStudio.scriptNode.batchVideo", "批量生视频")}</h3>
          <button
            type="button"
            aria-label={t("common.close", "关闭")}
            onClick={() =>
              storyboardWorkflow.handleCloseStoryboardVideoDialog(node)
            }
          >
            <X size={18} />
          </button>
        </header>
        <p className={styles.storyboardBatchHint}>
          {t(
            "aigcStudio.scriptNode.batchVideoHint",
            "会优先使用已生成的角色、场景和道具参考图，让视频更贴合分镜内容",
          )}
        </p>
        <p className={styles.storyboardBatchSubhint}>
          {t(
            "aigcStudio.scriptNode.batchVideoSubhint",
            "音频已默认开启，品质跟随视频品质。每镜时长为本次生成临时值，不写回剧本表格。",
          )}
        </p>
        <div className={styles.storyboardBatchList}>
          {shots.map((shot) => (
            <label
              key={shot.id}
              className={`${styles.storyboardBatchRow} ${styles.storyboardVideoBatchRow}`}
            >
              <input
                type="checkbox"
                checked={selectedIds.has(shot.id)}
                onChange={(event) =>
                  storyboardWorkflow.handleToggleStoryboardVideoShot(
                    node,
                    shot.id,
                    event.target.checked,
                  )
                }
              />
              <Check size={13} />
              <strong>
                {t("aigcStudio.scriptNode.shotNo", "镜头 {{no}}", {
                  no: shot.no,
                })}
              </strong>
              <em>{shot.videoPrompt || shot.prompt}</em>
              <button type="button">
                {t("aigcStudio.scriptNode.details", "详情")}
              </button>
              <span className={styles.storyboardBatchShotDuration}>
                {videoDurationForShot(node, shot.id)}s
              </span>
            </label>
          ))}
        </div>
        <footer className={styles.storyboardBatchFooter}>
          <label className={styles.storyboardBatchAll}>
            <input
              type="checkbox"
              checked={allSelected}
              onChange={(event) =>
                storyboardWorkflow.handleToggleAllStoryboardVideoShots(
                  node,
                  event.target.checked,
                )
              }
            />
            <Check size={13} />
            <span>
              {t(
                "aigcStudio.scriptNode.selectedShots",
                "已选 {{count}}/{{all}}",
                {
                  count: selectedCount,
                  all: shots.length,
                },
              )}
            </span>
          </label>
          <span className={styles.storyboardBatchOption}>
            <Film size={14} />
            {String(
              node.data.storyboardVideoModel ??
                t("aigcStudio.videoNode.noModel", "未选择视频模型"),
            )}
            <ChevronDown size={13} />
          </span>
          <span className={styles.storyboardBatchOption}>
            {String(node.data.storyboardVideoAspectRatio ?? "16:9")}
            <ChevronDown size={13} />
          </span>
          <span className={styles.storyboardBatchOption}>
            <Monitor size={14} />
            {String(node.data.storyboardVideoResolution ?? "720P")}
            <ChevronDown size={13} />
          </span>
          <button
            type="button"
            className={styles.storyboardBatchSubmit}
            disabled={selectedCount === 0 || pending}
            onClick={() =>
              storyboardWorkflow.handleGenerateStoryboardVideos(node)
            }
          >
            {pending ? (
              <>
                <Loader2 size={14} />
                {t(
                  "aigcStudio.scriptNode.videoBatchCreating",
                  "真人校验并创建中",
                )}
              </>
            ) : (
              t(
                "aigcStudio.scriptNode.confirmCreateVideoGroup",
                "确认并创建视频生成器组 ({{count}})",
                { count: selectedCount },
              )
            )}
          </button>
        </footer>
      </section>
    </div>
  );
}
