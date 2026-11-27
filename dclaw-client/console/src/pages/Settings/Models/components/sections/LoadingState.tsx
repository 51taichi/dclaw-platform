import { Button } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import FeedbackState from "@/components/FeedbackState";

interface LoadingStateProps {
  message: string;
  error?: boolean;
  onRetry?: () => void;
  className?: string;
}

export function LoadingState({
  message,
  error,
  onRetry,
  className,
}: LoadingStateProps) {
  const { t } = useTranslation();

  return (
    <FeedbackState
      variant={error ? "error" : "loading"}
      compact
      fill
      className={className}
      title={message}
      action={
        error && onRetry ? (
          <Button onClick={onRetry}>{t("models.retry")}</Button>
        ) : undefined
      }
    />
  );
}
