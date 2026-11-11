import styles from "./index.module.less";
import { useTranslation } from "react-i18next";
import FeedbackState from "../../../../components/FeedbackState";

export type PreparingOverlayMode = "task" | "conversation";

export default function PreparingOverlay({
  mode = "task",
}: {
  mode?: PreparingOverlayMode;
}) {
  const { t } = useTranslation();
  const isConversation = mode === "conversation";

  return (
    <div className={styles.overlay}>
      <FeedbackState
        variant="loading"
        compact
        className={styles.feedback}
        title={
          isConversation
            ? t("taskLoading.conversationTitle", "正在恢复会话")
            : t("taskLoading.taskTitle", "正在准备任务")
        }
        description={
          isConversation
            ? t(
                "taskLoading.conversationSubtitle",
                "正在加载历史消息与任务状态，请稍候",
              )
            : t("taskLoading.taskSubtitle", "Agent 正在进入工作状态，请稍候")
        }
        action={
          <div className={styles.progressBar} aria-hidden="true">
            <div className={styles.progressInner} />
          </div>
        }
      />
    </div>
  );
}
