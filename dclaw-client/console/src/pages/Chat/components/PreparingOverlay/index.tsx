import styles from "./index.module.less";
import { useTranslation } from "react-i18next";
import FeedbackState from "../../../../components/FeedbackState";
import { Button } from "antd";

export type PreparingOverlayMode = "task" | "conversation";

export default function PreparingOverlay({
  mode = "task",
  error = false,
  onRetry,
}: {
  mode?: PreparingOverlayMode;
  error?: boolean;
  onRetry?: () => void;
}) {
  const { t } = useTranslation();
  const isConversation = mode === "conversation";

  if (error) {
    return (
      <div className={styles.overlay}>
        <FeedbackState
          variant="error"
          compact
          className={styles.feedback}
          title={t("taskLoading.restoreFailed", "会话历史加载失败")}
          description={t(
            "taskLoading.restoreFailedSubtitle",
            "历史记录仍然保留在服务器，请重试加载。",
          )}
          action={
            onRetry ? (
              <Button type="primary" onClick={onRetry}>
                {t("taskLoading.retry", "重试")}
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

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
