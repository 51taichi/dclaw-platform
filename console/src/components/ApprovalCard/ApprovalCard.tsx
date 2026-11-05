import { useEffect, useState } from "react";
import { Check, Clock, Shield, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./ApprovalCard.module.less";
export interface ApprovalCardProps {
  requestId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
  agentId: string;
  ownerAgentId?: string;
  showInboxAgentContext?: boolean;
  showParamsExpanded?: boolean;
  sessionId?: string;
  rootSessionId?: string;
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel?: () => void;
  onAcknowledge?: (requestId: string) => Promise<void>;
}

export function ApprovalCard({
  requestId,
  severity,
  createdAt,
  timeoutSeconds,
  onApprove,
  onDeny,
  onCancel,
  onAcknowledge,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState<
    "approve" | "deny" | "acknowledge" | null
  >(null);
  const [remaining, setRemaining] = useState<number>(timeoutSeconds);
  const isTimedOut = remaining <= 0;
  const normalizedSeverity = severity.toLowerCase();
  const isSensitiveOperation = ["medium", "high", "critical"].includes(
    normalizedSeverity,
  );

  useEffect(() => {
    const elapsed = Date.now() / 1000 - createdAt;
    const initialRemaining = Math.max(0, Math.floor(timeoutSeconds - elapsed));
    setRemaining(initialRemaining);

    const timer = setInterval(() => {
      const newElapsed = Date.now() / 1000 - createdAt;
      const newRemaining = Math.max(0, Math.floor(timeoutSeconds - newElapsed));
      setRemaining(newRemaining);

      if (newRemaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [createdAt, timeoutSeconds]);

  const handleApprove = async () => {
    console.log("[ApprovalCard] Approve button clicked:", requestId);
    setLoading("approve");
    try {
      await onApprove(requestId);
      console.log("[ApprovalCard] onApprove completed");
    } catch (err) {
      console.error("[ApprovalCard] onApprove failed:", err);
    } finally {
      setLoading(null);
    }
  };

  const handleDeny = async () => {
    setLoading("deny");
    try {
      await onDeny(requestId);
    } finally {
      setLoading(null);
    }
  };

  const handleAcknowledge = async () => {
    if (!onAcknowledge) return;
    setLoading("acknowledge");
    try {
      await onAcknowledge(requestId);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className={styles.approvalCard}>
      <div className={styles.header}>
        <div className={styles.titleRow}>
          <Shield size={18} className={styles.icon} />
          <span className={styles.title}>
            {t("approval.title", "Your authorization is required")}
          </span>
        </div>
        <div className={styles.timer}>
          <Clock size={14} className={styles.timerIcon} />
          <span className={styles.timerText}>
            {Math.floor(remaining / 60)}:
            {String(remaining % 60).padStart(2, "0")}
          </span>
        </div>
      </div>

      <div className={styles.content}>
        <p className={styles.reason}>
          {isSensitiveOperation
            ? t(
                "approval.sensitiveReason",
                "This operation may read, modify, or delete local data. To protect your data, your explicit authorization is required. Allow it to continue?",
              )
            : t(
                "approval.reason",
                "This operation needs access to local resources. To protect your data, your authorization is required. Allow it to continue?",
              )}
        </p>
      </div>

      <div className={styles.actions}>
        {isTimedOut ? (
          <>
            <span className={styles.timeoutHint}>
              {t("approval.timeoutAutoDenied", "Timed out, auto denied")}
            </span>
            {onAcknowledge ? (
              <button
                className={styles.approveButton}
                onClick={handleAcknowledge}
                disabled={loading !== null}
              >
                {loading === "acknowledge" ? (
                  <span
                    className="animate-spin"
                    style={{ display: "inline-block" }}
                  >
                    ⏳
                  </span>
                ) : (
                  <Check size={14} />
                )}
                {t("approval.acknowledge", "Got It")}
              </button>
            ) : null}
          </>
        ) : (
          <>
            {onCancel && (
              <button
                className={styles.denyButton}
                onClick={() => {
                  console.log("[ApprovalCard] Cancel task button clicked");
                  onCancel();
                }}
                disabled={loading !== null}
              >
                {t("approval.cancelTask", "Cancel Task")}
              </button>
            )}
            <button
              className={styles.denyButton}
              onClick={handleDeny}
              disabled={loading !== null}
            >
              {loading === "deny" ? (
                <span
                  className="animate-spin"
                  style={{ display: "inline-block" }}
                >
                  ⏳
                </span>
              ) : (
                <X size={14} />
              )}
              {t("approval.deny", "Deny")}
            </button>
            <button
              className={styles.approveButton}
              onClick={handleApprove}
              disabled={loading !== null}
            >
              {loading === "approve" ? (
                <span
                  className="animate-spin"
                  style={{ display: "inline-block" }}
                >
                  ⏳
                </span>
              ) : (
                <Check size={14} />
              )}
              {t("approval.approve", "Allow")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
