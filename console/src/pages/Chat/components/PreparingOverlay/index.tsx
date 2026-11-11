import styles from "./index.module.less";
import { useTranslation } from "react-i18next";

export type PreparingOverlayMode = "task" | "conversation";

export default function PreparingOverlay({
  mode = "task",
}: {
  mode?: PreparingOverlayMode;
}) {
  const { t } = useTranslation();
  const isConversation = mode === "conversation";

  return (
    <div
      className={styles.overlay}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className={styles.content}>
        <img src="/mascot.png" alt="" className={styles.mascot} />
        <h2 className={styles.title}>
          {isConversation
            ? t("taskLoading.conversationTitle", "正在恢复会话")
            : t("taskLoading.taskTitle", "正在准备任务")}
        </h2>
        <p className={styles.subtitle}>
          {isConversation
            ? t(
                "taskLoading.conversationSubtitle",
                "正在加载历史消息与任务状态，请稍候",
              )
            : t("taskLoading.taskSubtitle", "Agent 正在进入工作状态，请稍候")}
        </p>
        <div className={styles.progressBar}>
          <div className={styles.progressInner} />
        </div>
      </div>
    </div>
  );
}
