import { Download, FileVideo2, Images, Loader2 } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import type { Translate } from "./types";

type ScriptToolbarProps = {
  node: AigcCanvasNode;
  t: Translate;
  onRegenerate: (node: AigcCanvasNode) => void;
  onGenerateStoryboard: (node: AigcCanvasNode) => void;
  onGenerateVideo: (node: AigcCanvasNode) => void;
};

export function ScriptToolbar({
  node,
  t,
  onRegenerate,
  onGenerateStoryboard,
  onGenerateVideo,
}: ScriptToolbarProps) {
  return (
    <div
      className={styles.scriptActionToolbar}
      data-testid="aigc-script-ready-toolbar"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        data-testid="aigc-script-regenerate"
        aria-label={t("aigcStudio.scriptNode.regenerate", "重新生成")}
        onClick={() => onRegenerate(node)}
      >
        <Loader2 size={18} />
        {t("aigcStudio.scriptNode.regenerate", "重新生成")}
      </button>
      <button
        type="button"
        data-testid="aigc-script-generate-storyboard"
        aria-label={t(
          "aigcStudio.scriptNode.generateStoryboard",
          "批量生成分镜",
        )}
        onClick={() => onGenerateStoryboard(node)}
      >
        <Images size={18} />
        {t("aigcStudio.scriptNode.generateStoryboard", "批量生成分镜")}
      </button>
      <button
        type="button"
        aria-label={t("aigcStudio.scriptNode.batchVideo", "批量生视频")}
        onClick={() => onGenerateVideo(node)}
      >
        <FileVideo2 size={18} />
        {t("aigcStudio.scriptNode.batchVideo", "批量生视频")}
      </button>
      <button
        type="button"
        aria-label={t("aigcStudio.scriptNode.download", "下载")}
      >
        <Download size={18} />
      </button>
    </div>
  );
}
