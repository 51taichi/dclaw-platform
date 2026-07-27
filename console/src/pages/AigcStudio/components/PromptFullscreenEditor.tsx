import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import styles from "../index.module.less";

type PromptFullscreenEditorProps = {
  open: boolean;
  title: string;
  label: string;
  value: string;
  placeholder: string;
  closeLabel: string;
  meta?: string;
  onChange: (value: string) => void;
  onClose: () => void;
};

export function PromptFullscreenEditor({
  open,
  title,
  label,
  value,
  placeholder,
  closeLabel,
  meta,
  onChange,
  onClose,
}: PromptFullscreenEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className={styles.composerFullscreenOverlay}
      data-aigc-floating-panel
      data-testid="aigc-composer-fullscreen-editor"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <section className={styles.composerFullscreenDialog}>
        <header className={styles.composerFullscreenHeader}>
          <strong>{title}</strong>
          <button type="button" aria-label={closeLabel} onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <textarea
          ref={textareaRef}
          className={styles.composerFullscreenTextarea}
          value={value}
          placeholder={placeholder}
          aria-label={label}
          onChange={(event) => onChange(event.target.value)}
        />
        {meta ? (
          <footer className={styles.composerFullscreenFooter}>{meta}</footer>
        ) : null}
      </section>
    </div>,
    document.body,
  );
}
