import styles from "./RunningSessionNotice.module.less";

interface RunningSessionNoticeProps {
  visible: boolean;
  variant?: "floating" | "inline";
}

export default function RunningSessionNotice({
  visible,
  variant = "floating",
}: RunningSessionNoticeProps) {
  if (!visible) return null;

  return (
    <div
      className={`${styles.notice} ${
        variant === "inline" ? styles.noticeInline : ""
      }`}
      role="status"
      aria-live="polite"
    >
      <span className={styles.pulse} aria-hidden="true" />
      <div className={styles.copy}>
        <span className={styles.title}>DClaw 正在继续生成</span>
        <span className={styles.description}>
          切换回来后会自动同步结果，你可以放心去看别的任务。
        </span>
      </div>
    </div>
  );
}
