import { Button } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import FeedbackState from "@/components/FeedbackState";

interface LoadingStateProps {
  message: string;
  error?: boolean;
  onRetry?: () => void;
  className?: string;
  fill?: boolean;
}

export function LoadingState({
  message,
  error,
  onRetry,
  className,
  fill = false,
}: LoadingStateProps) {
  const { t } = useTranslation();

  return (
    <FeedbackState
      variant={error ? "error" : "loading"}
      compact
      fill={fill}
      className={className}
      title={message}
      action={
        error && onRetry ? (
          <Button onClick={onRetry}>{t("common.refresh")}</Button>
        ) : undefined
      }
    />
  );
}
