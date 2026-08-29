import { Alert, Button, Space } from "antd";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { InsufficientCreditsFailure } from "../../api/types/billing";

interface BillingFailureAlertProps {
  failure: InsufficientCreditsFailure;
  pausedRunId?: string | null;
  onContinue?: (runId: string) => Promise<void>;
}

export default function BillingFailureAlert({
  failure,
  pausedRunId,
  onContinue,
}: BillingFailureAlertProps) {
  const { t } = useTranslation();
  const [continuing, setContinuing] = useState(false);
  const [continueError, setContinueError] = useState(false);
  const continuingRef = useRef(false);

  const continueRun = async () => {
    if (!pausedRunId || !onContinue || continuingRef.current) return;
    continuingRef.current = true;
    setContinuing(true);
    setContinueError(false);
    try {
      await onContinue(pausedRunId);
    } catch {
      setContinueError(true);
    } finally {
      continuingRef.current = false;
      setContinuing(false);
    }
  };

  return (
    <Alert
      type="warning"
      showIcon
      message={t("billing.insufficientTitle")}
      description={
        <Space direction="vertical" size={8}>
          <span>
            {t("billing.balanceRequired", {
              available: failure.available_credits.toLocaleString(),
              required: failure.required_credits.toLocaleString(),
            })}
          </span>
          {continueError && <span>{t("billing.continueFailed")}</span>}
          <Space>
            <Link to={failure.top_up_path}>{t("billing.topUp")}</Link>
            {pausedRunId && onContinue && (
              <Button
                type="primary"
                loading={continuing}
                disabled={continuing}
                aria-label={t("billing.continueAfterTopUp")}
                onClick={() => void continueRun()}
              >
                {t("billing.continueAfterTopUp")}
              </Button>
            )}
          </Space>
        </Space>
      }
    />
  );
}
