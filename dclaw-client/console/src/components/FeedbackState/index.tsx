import type { ReactNode } from "react";
import apologyMascot from "../../assets/feedback/dclaw-apology.png";
import frustratedMascot from "../../assets/feedback/dclaw-frustrated.png";
import loadingMascot from "../../assets/feedback/dclaw-loading.png";
import styles from "./index.module.less";

export type FeedbackStateVariant = "loading" | "error" | "apology";

const mascotByVariant: Record<FeedbackStateVariant, string> = {
  loading: loadingMascot,
  error: frustratedMascot,
  apology: apologyMascot,
};

interface FeedbackStateProps {
  variant: FeedbackStateVariant;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  fill?: boolean;
  className?: string;
}

export default function FeedbackState({
  variant,
  title,
  description,
  action,
  compact = false,
  fill = false,
  className,
}: FeedbackStateProps) {
  const isLoading = variant === "loading";
  const rootClassName = [
    styles.root,
    compact ? styles.compact : "",
    fill ? styles.fill : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section
      className={rootClassName}
      data-feedback-state={variant}
      role={isLoading ? "status" : "alert"}
      aria-live={isLoading ? "polite" : "assertive"}
      aria-busy={isLoading || undefined}
    >
      <img
        src={mascotByVariant[variant]}
        alt=""
        aria-hidden="true"
        className={styles.image}
      />
      <h2 className={styles.title}>{title}</h2>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </section>
  );
}
