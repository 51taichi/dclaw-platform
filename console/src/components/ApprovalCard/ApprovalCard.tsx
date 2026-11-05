import { useState, useEffect, useCallback, useMemo } from "react";
import { Tag } from "antd";
import { Shield, Check, X, Clock, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../stores/agentStore";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
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
  toolName,
  severity,
  findingsCount,
  findingsSummary,
  toolParams,
  createdAt,
  timeoutSeconds,
  agentId,
  ownerAgentId,
  showInboxAgentContext = false,
  showParamsExpanded = false,
  sessionId,
  rootSessionId,
  onApprove,
  onDeny,
  onCancel,
  onAcknowledge,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
  const [loading, setLoading] = useState<
    "approve" | "deny" | "acknowledge" | null
  >(null);
  const [remaining, setRemaining] = useState<number>(timeoutSeconds);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const handleCopy = useCallback(async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 1500);
    } catch {
      /* clipboard not available */
    }
  }, []);

  // Check if this is a cross-session approval
  const isCrossSession =
    sessionId && rootSessionId && sessionId !== rootSessionId;
  const isTimedOut = remaining <= 0;
  const executionAgentDisplayName = useMemo(() => {
    const matched = agentsById.get(agentId);
    if (matched) return getAgentDisplayName(matched, t);
    return agentId || t("common.unknown", "Unknown");
  }, [agentsById, agentId, t]);
  const ownerAgentDisplayName = useMemo(() => {
    const ownerId = ownerAgentId || agentId;
    const matched = agentsById.get(ownerId);
    if (matched) return getAgentDisplayName(matched, t);
    return ownerId || t("common.unknown", "Unknown");
  }, [agentsById, ownerAgentId, agentId, t]);
  const shouldShowExecutionAgent =
    showInboxAgentContext && Boolean(isCrossSession);

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

  const getSeverityColor = (sev: string) => {
    const s = sev.toLowerCase();
    if (s === "critical" || s === "high") return "error";
    if (s === "medium") return "warning";
    return "default";
  };

  return (
    <div className={`${styles.approvalCard} ${styles[getSeverityColor(severity)]}`}>
      <div className={styles.header}>
        <div className={styles.titleRow}>
          <Shield size={18} className={styles.icon} />
          <span className={styles.title}>
            {t("approval.title", "Security Approval Required")}
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
        {showInboxAgentContext ? (
          <>
            <div className={styles.infoRow}>
              <span className={styles.label}>
                {t("approval.ownerAgent", "Owner Agent")}:
              </span>
              <Tag color="success" className={styles.ownerAgentTag}>
                {ownerAgentDisplayName}
              </Tag>
            </div>
            {shouldShowExecutionAgent ? (
              <div className={styles.infoRow}>
                <span className={styles.label}>
                  {t("approval.executingAgent", "Executing Agent")}:
                </span>
                <Tag color="blue" className={styles.crossSessionTag}>
                  {executionAgentDisplayName}
                </Tag>
              </div>
            ) : null}
          </>
        ) : null}

        <div className={styles.infoRow}>
          <span className={styles.label}>{t("approval.tool", "Tool")}:</span>
          <span className={styles.value}>
            <code>{toolName}</code>
          </span>
        </div>

        <div className={styles.infoRow}>
          <span className={styles.label}>
            {t("approval.severity", "Severity")}:
          </span>
          <Tag
            color={getSeverityColor(severity)}
            className={styles.severityTag}
          >
            {severity.toUpperCase()}
          </Tag>
        </div>

        <div className={styles.infoRow}>
          <span className={styles.label}>
            {t("approval.findings", "Findings")}:
          </span>
          <span className={styles.value}>{findingsCount}</span>
        </div>

        {isCrossSession && !showInboxAgentContext && (
          <div className={styles.infoRow}>
            <span className={styles.label}>
              {t("approval.source", "Source")}:
            </span>
            <Tag color="blue" className={styles.crossSessionTag}>
              {t("approval.subSession", "Sub-Agent")} ({sessionId?.slice(0, 8)})
            </Tag>
          </div>
        )}

        {findingsSummary && (
          <div className={styles.summaryBox}>
            <span className={styles.summaryText}>{findingsSummary}</span>
            <button
              className={`${styles.copyButton} ${
                copiedField === "summary" ? styles.copied : ""
              }`}
              onClick={() => handleCopy(findingsSummary, "summary")}
              title={t("common.copy", "Copy")}
            >
              <Copy size={12} />
            </button>
          </div>
        )}

        {toolParams && Object.keys(toolParams).length > 0 && (
          <details className={styles.paramsDetails} open={showParamsExpanded}>
            <summary className={styles.paramsSummary}>
              {t("approval.parameters", "Parameters")}
            </summary>
            <div className={styles.paramsCodeWrapper}>
              <pre className={styles.paramsCode}>
                {JSON.stringify(toolParams, null, 2)}
              </pre>
              <button
                className={`${styles.copyButton} ${
                  copiedField === "params" ? styles.copied : ""
                }`}
                onClick={() =>
                  handleCopy(JSON.stringify(toolParams, null, 2), "params")
                }
                title={t("common.copy", "Copy")}
              >
                <Copy size={12} />
              </button>
            </div>
          </details>
        )}
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
                  <span className="animate-spin" style={{ display: "inline-block" }}>⏳</span>
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
                <span className="animate-spin" style={{ display: "inline-block" }}>⏳</span>
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
                <span className="animate-spin" style={{ display: "inline-block" }}>⏳</span>
              ) : (
                <Check size={14} />
              )}
              {t("approval.approve", "Approve")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
