import { Play, X } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import {
  scriptSelectedStoryboardVideoShotIds,
  scriptStoryboardImageShotIds,
} from "../ScriptNode/scriptNodeState";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";

type StoryboardVideoComposerProps = {
  node: AigcCanvasNode;
  t: Translate;
  storyboardWorkflow: StoryboardWorkflow;
  onClose: () => void;
};

export function StoryboardVideoComposer({
  node,
  t,
  storyboardWorkflow,
  onClose,
}: StoryboardVideoComposerProps) {
  const selectedCount = scriptSelectedStoryboardVideoShotIds(node).length;
  const allCount = scriptStoryboardImageShotIds(node).length;
  const allSelected = selectedCount === allCount && allCount > 0;

  return (
    <div
      className={styles.storyboardVideoComposer}
      data-testid="aigc-storyboard-video-composer"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className={styles.storyboardClose}
        aria-label={t("aigcStudio.scriptNode.closeVideoConfig", "关闭视频配置")}
        onClick={(event) => {
          event.stopPropagation();
          onClose();
        }}
      >
        <X size={16} />
      </button>
      <label className={styles.storyboardSelectAllButton}>
        <input
          type="checkbox"
          aria-label={t("aigcStudio.scriptNode.selectAllImages", "全选分镜图")}
          checked={allSelected}
          onChange={(event) =>
            storyboardWorkflow.handleToggleAllStoryboardVideoShots(
              node,
              event.target.checked,
            )
          }
        />
        {allSelected
          ? t(
              "aigcStudio.scriptNode.allSelectedImages",
              "全选 {{count}}个分镜",
              {
                count: allCount,
              },
            )
          : t(
              "aigcStudio.scriptNode.selectedImages",
              "已选 {{selected}}/{{all}} 个分镜",
              {
                selected: selectedCount,
                all: allCount,
              },
            )}
      </label>
      <div className={styles.storyboardParamBar}>
        <span>
          {String(
            node.data.storyboardVideoModel ??
              t("aigcStudio.videoNode.noModel", "未选择视频模型"),
          )}
        </span>
        <span>{String(node.data.storyboardVideoAspectRatio ?? "1:1")}</span>
        <span>
          {t("aigcStudio.scriptNode.videoDuration", "{{seconds}}s", {
            seconds: Number(node.data.storyboardVideoDuration ?? 5),
          })}
        </span>
        <span>{t("aigcStudio.scriptNode.batchVideo", "批量视频")}</span>
        <span>✦ 825</span>
        <button
          type="button"
          className={styles.runCircle}
          aria-label={t(
            "aigcStudio.scriptNode.submitBatchVideo",
            "提交批量视频生成",
          )}
          disabled={selectedCount === 0}
          onClick={(event) => {
            event.stopPropagation();
            storyboardWorkflow.handleGenerateStoryboardVideos(node);
          }}
        >
          <Play size={15} />
        </button>
      </div>
    </div>
  );
}
