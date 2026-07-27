import { Boxes, Image } from "lucide-react";

import styles from "../../index.module.less";
import type { NodePreviewBlocksProps } from "./types";

export function NodePreviewBlocks({ node, t }: NodePreviewBlocksProps) {
  return (
    <>
      {node.data.previewKind === "script" && (
        <div className={styles.scriptPreview}>
          {String(node.data.text ?? "")
            .split("\n")
            .map((line) => (
              <span key={line}>{line}</span>
            ))}
        </div>
      )}
      {node.data.previewKind === "characterPortrait" && (
        <div className={`${styles.assetPreview} ${styles.assetCharacter}`} />
      )}
      {node.data.previewKind === "turnaround" && (
        <div className={`${styles.assetPreview} ${styles.assetTurnaround}`} />
      )}
      {node.data.previewKind === "keyframe" && (
        <div className={`${styles.assetPreview} ${styles.assetKeyframe}`} />
      )}
      {node.data.previewKind === "portrait" && (
        <div className={`${styles.assetPreview} ${styles.assetPortrait}`} />
      )}
      {node.type === "image_generate" && !node.data.previewKind && (
        <div className={styles.previewBlock}>
          <Image size={38} />
        </div>
      )}
      {(node.type === "video_generate" || node.type === "video_compose") && (
        <div className={styles.videoBlock}>16:9</div>
      )}
      {node.type === "director_stage" && (
        <div className={styles.stageBlock}>
          <Boxes size={34} />
          <span>{t("aigcStudio.openStage", "打开导演台")}</span>
        </div>
      )}
    </>
  );
}
