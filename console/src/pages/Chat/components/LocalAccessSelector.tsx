import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Hand, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import sessionApi, {
  DRAFT_SESSION_ID,
  DEFAULT_LOCAL_ACCESS_MODE,
  type LocalAccessMode,
} from "../sessionApi";
import styles from "./LocalAccessSelector.module.less";

interface LocalAccessSelectorProps {
  chatId?: string | null;
  agentId?: string;
  disabled?: boolean;
  onOpen?: () => void;
}

export default function LocalAccessSelector({
  chatId,
  agentId,
  disabled = false,
  onOpen,
}: LocalAccessSelectorProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const rootRef = useRef<HTMLDivElement>(null);
  const selectionVersionRef = useRef(0);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<LocalAccessMode>(DEFAULT_LOCAL_ACCESS_MODE);
  const resolvedChatId = chatId || DRAFT_SESSION_ID;

  useEffect(() => {
    let cancelled = false;
    const selectionVersion = selectionVersionRef.current;
    void sessionApi
      .getLocalAccessMode(resolvedChatId)
      .then((value) => {
        if (!cancelled && selectionVersionRef.current === selectionVersion) {
          setMode(value);
        }
      })
      .catch(() => {
        if (!cancelled && selectionVersionRef.current === selectionVersion) {
          setMode(DEFAULT_LOCAL_ACCESS_MODE);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [resolvedChatId]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const selectMode = async (nextMode: LocalAccessMode) => {
    if (nextMode === mode) {
      setOpen(false);
      return;
    }
    selectionVersionRef.current += 1;
    setSaving(true);
    try {
      const saved = await sessionApi.setLocalAccessMode(
        resolvedChatId,
        nextMode,
        agentId,
      );
      setMode(saved);
      setOpen(false);
    } catch {
      void message.error(
        t("chatToolbar.localAccess.saveFailed", "权限设置保存失败"),
      );
    } finally {
      setSaving(false);
    }
  };

  const isFullAccess = mode === "full_access";
  const triggerLabel = isFullAccess
    ? t("chatToolbar.localAccess.fullAccess", "允许完全访问")
    : t("chatToolbar.localAccess.askApproval", "操作前询问");

  return (
    <div ref={rootRef} className={styles.root}>
      <button
        type="button"
        className={`${styles.trigger} ${
          isFullAccess ? styles.triggerFullAccess : ""
        }`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={triggerLabel}
        disabled={disabled || saving}
        onClick={() => {
          const nextOpen = !open;
          setOpen(nextOpen);
          if (nextOpen) onOpen?.();
        }}
      >
        <ShieldAlert size={14} />
        <span>{triggerLabel}</span>
        <ChevronDown size={12} className={styles.chevron} />
      </button>

      {open && (
        <div className={styles.menu} role="menu">
          <div className={styles.menuTitle}>
            {t(
              "chatToolbar.localAccess.question",
              "DClaw 执行操作时应如何获得批准？",
            )}
          </div>

          <button
            type="button"
            role="menuitemradio"
            aria-checked={mode === "ask_for_approval"}
            className={styles.option}
            onClick={() => void selectMode("ask_for_approval")}
          >
            <Hand size={20} className={styles.optionIcon} />
            <span className={styles.optionText}>
              <span className={styles.optionLabel}>
                {t("chatToolbar.localAccess.askApproval", "操作前询问")}
              </span>
              <span className={styles.optionDescription}>
                {t(
                  "chatToolbar.localAccess.askApprovalDescription",
                  "执行工具操作前始终请求你的批准",
                )}
              </span>
            </span>
            {mode === "ask_for_approval" && (
              <Check size={18} className={styles.check} />
            )}
          </button>

          <button
            type="button"
            role="menuitemradio"
            aria-checked={mode === "full_access"}
            className={`${styles.option} ${styles.fullAccessOption}`}
            onClick={() => void selectMode("full_access")}
          >
            <ShieldAlert size={20} className={styles.optionIcon} />
            <span className={styles.optionText}>
              <span className={styles.optionLabel}>
                {t("chatToolbar.localAccess.fullAccess", "允许完全访问")}
              </span>
              <span className={styles.optionDescription}>
                {t(
                  "chatToolbar.localAccess.fullAccessDescription",
                  "不受限制地执行工具操作，不再请求批准",
                )}
              </span>
            </span>
            {mode === "full_access" && (
              <Check size={18} className={styles.check} />
            )}
          </button>
        </div>
      )}
    </div>
  );
}
