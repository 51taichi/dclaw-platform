import styles from "./index.module.less";

export default function PreparingOverlay() {
  return (
    <div className={styles.overlay}>
      <div className={styles.content}>
        <img src="/mascot.png" alt="Mascot" className={styles.mascot} />
        <h2 className={styles.title}>正在准备执行</h2>
        <p className={styles.subtitle}>Agent 正在握手并进入工作状态...</p>
        <div className={styles.progressBar}>
          <div className={styles.progressInner} />
        </div>
      </div>
    </div>
  );
}
