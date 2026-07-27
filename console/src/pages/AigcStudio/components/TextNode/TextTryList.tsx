import { AudioLines, FileText, Film, Image } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import type { TextTryAction, Translate } from "./types";

const tryActions = [
  {
    action: "write",
    key: "write",
    fallback: "自己编写内容",
    icon: <FileText size={15} />,
  },
  {
    action: "text_to_video",
    key: "textToVideo",
    fallback: "文生视频",
    icon: <Film size={15} />,
  },
  {
    action: "image_to_prompt",
    key: "imageToPrompt",
    fallback: "图片反推提示词",
    icon: <Image size={15} />,
  },
  {
    action: "text_to_music",
    key: "textToMusic",
    fallback: "文字生音乐",
    icon: <AudioLines size={15} />,
  },
] as const;

type TextTryListProps = {
  node: AigcCanvasNode;
  t: Translate;
  onTry: (node: AigcCanvasNode, action: TextTryAction) => void;
};

export function TextTryList({ node, t, onTry }: TextTryListProps) {
  return (
    <div className={styles.textTryList}>
      <div className={styles.textTryTitle}>
        {t("aigcStudio.textNode.tryTitle", "尝试：")}
      </div>
      {tryActions.map((item) => (
        <button
          type="button"
          key={item.action}
          className={styles.textTryButton}
          onClick={(event) => {
            event.stopPropagation();
            onTry(node, item.action);
          }}
        >
          {item.icon}
          {t(`aigcStudio.textNode.try.${item.key}`, item.fallback)}
        </button>
      ))}
    </div>
  );
}
