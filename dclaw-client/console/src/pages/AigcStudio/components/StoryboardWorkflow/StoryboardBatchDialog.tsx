import { Check, ChevronDown, Image, X } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import {
  scriptSelectedShotIds,
  scriptShotsFromNode,
} from "../ScriptNode/scriptNodeState";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";

type StoryboardBatchDialogProps = {
  node: AigcCanvasNode;
  t: Translate;
  storyboardWorkflow: StoryboardWorkflow;
};

export function StoryboardBatchDialog({
  node,
  t,
  storyboardWorkflow,
}: StoryboardBatchDialogProps) {
  const shots = scriptShotsFromNode(node);
  const selectedIds = new Set(scriptSelectedShotIds(node));
  const selectedCount = selectedIds.size;
  const allSelected = shots.length > 0 && selectedCount === shots.length;

  return (
    <div
      className={styles.storyboardBatchDialogOverlay}
      onClick={(event) => event.stopPropagation()}
    >
      <section
        role="dialog"
        aria-label={t(
          "aigcStudio.scriptNode.batchStoryboardTitle",
          "分镜批量生图",
        )}
        className={styles.storyboardBatchDialog}
      >
        <header className={styles.storyboardBatchHeader}>
          <h3>
            {t("aigcStudio.scriptNode.batchStoryboardTitle", "分镜批量生图")}
          </h3>
          <button
            type="button"
            aria-label={t("common.close", "关闭")}
            onClick={() =>
              storyboardWorkflow.handleCloseStoryboardComposer(node)
            }
          >
            <X size={18} />
          </button>
        </header>
        <p className={styles.storyboardBatchHint}>
          {t(
            "aigcStudio.scriptNode.batchStoryboardHint",
            "会优先使用已生成的角色、场景和道具参考图，让画面更贴合分镜内容",
          )}
        </p>
        <div className={styles.storyboardBatchList}>
          {shots.map((shot) => (
            <label key={shot.id} className={styles.storyboardBatchRow}>
              <input
                type="checkbox"
                checked={selectedIds.has(shot.id)}
                onChange={(event) =>
                  storyboardWorkflow.handleToggleScriptShot(
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
              <span>{shot.shotType}</span>
              <em>{shot.prompt}</em>
              <button type="button">
                {t("aigcStudio.scriptNode.details", "详情")}
              </button>
            </label>
          ))}
        </div>
        <footer className={styles.storyboardBatchFooter}>
          <label className={styles.storyboardBatchAll}>
            <input
              type="checkbox"
              checked={allSelected}
              onChange={(event) =>
                storyboardWorkflow.handleToggleAllScriptShots(
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
            <Image size={14} />
            {String(node.data.storyboardStyle ?? "Lib Image")}
            <ChevronDown size={13} />
          </span>
          <span className={styles.storyboardBatchOption}>medium</span>
          <span className={styles.storyboardBatchOption}>2K</span>
          <span className={styles.storyboardBatchOption}>auto</span>
          <button
            type="button"
            className={styles.storyboardBatchSubmit}
            disabled={selectedCount === 0}
            onClick={() =>
              storyboardWorkflow.handleStoryboardComposerSubmit(node)
            }
          >
            {t(
              "aigcStudio.scriptNode.confirmCreateStoryboardGroup",
              "确认并创建生成器组 ({{count}})",
              { count: selectedCount },
            )}
          </button>
        </footer>
      </section>
    </div>
  );
}
