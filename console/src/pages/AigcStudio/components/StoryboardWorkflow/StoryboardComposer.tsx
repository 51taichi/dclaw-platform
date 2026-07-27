import { Camera, Play, Sparkles, X } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import {
  scriptSelectedShotIds,
  scriptShotsFromNode,
} from "../ScriptNode/scriptNodeState";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";

type StoryboardComposerProps = {
  node: AigcCanvasNode;
  t: Translate;
  storyboardWorkflow: StoryboardWorkflow;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
};

export function StoryboardComposer({
  node,
  t,
  storyboardWorkflow,
  onUpdateNodeData,
}: StoryboardComposerProps) {
  const selectedCount = scriptSelectedShotIds(node).length;
  const allCount = scriptShotsFromNode(node).length;
  const styleName = String(node.data.storyboardStyle ?? "Lib Image");

  return (
    <div
      className={styles.storyboardComposer}
      data-testid="aigc-storyboard-composer"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className={styles.storyboardClose}
        aria-label={t(
          "aigcStudio.scriptNode.closeStoryboardConfig",
          "关闭分镜配置",
        )}
        onClick={(event) => {
          event.stopPropagation();
          storyboardWorkflow.handleCloseStoryboardComposer(node);
        }}
      >
        <X size={16} />
      </button>
      <button
        type="button"
        className={styles.storyboardStyleButton}
        aria-label={t("aigcStudio.scriptNode.style", "风格")}
        onClick={(event) => {
          event.stopPropagation();
          onUpdateNodeData(node.id, {
            storyboardStyleMenuOpen: node.data.storyboardStyleMenuOpen !== true,
          });
        }}
      >
        <Sparkles size={15} />
        {t("aigcStudio.scriptNode.style", "风格")}
      </button>
      {node.data.storyboardStyleMenuOpen === true && (
        <div className={styles.storyboardStyleMenu}>
          {["Lib Image", "古风水墨", "电影质感", "国潮插画"].map(
            (styleNameOption) => (
              <button
                type="button"
                key={styleNameOption}
                onClick={() =>
                  storyboardWorkflow.handleSelectStoryboardStyle(
                    node,
                    styleNameOption,
                  )
                }
              >
                <span />
                {styleNameOption}
              </button>
            ),
          )}
        </div>
      )}
      <div className={styles.storyboardParamBar}>
        <span>{styleName}</span>
        <span>{t("aigcStudio.scriptNode.autoRatio", "自适应")}</span>
        <span>标准画质</span>
        <span>2K</span>
        <span>
          <Camera size={14} />
          {t("aigcStudio.scriptNode.camera", "摄像机")}
        </span>
        <span>
          {t(
            "aigcStudio.scriptNode.selectedCount",
            "已选{{selected}}/{{all}}",
            {
              selected: selectedCount,
              all: allCount,
            },
          )}
        </span>
        <span>✦ 306</span>
        <button
          type="button"
          className={styles.runCircle}
          aria-label={t(
            "aigcStudio.scriptNode.submitStoryboard",
            "提交分镜生成",
          )}
          disabled={selectedCount === 0}
          onClick={(event) => {
            event.stopPropagation();
            storyboardWorkflow.handleStoryboardComposerSubmit(node);
          }}
        >
          <Play size={15} />
        </button>
      </div>
    </div>
  );
}
