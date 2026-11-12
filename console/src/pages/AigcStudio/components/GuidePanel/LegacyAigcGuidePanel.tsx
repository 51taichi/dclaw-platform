import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  LocateFixed,
  Pause,
  Play,
  RotateCcw,
} from "lucide-react";

import type {
  AigcOperationContract,
  BoundAigcTask,
} from "../../../../api/modules/superExpertPlatform";
import { focusPlatformControl, resolveControl } from "./controlRegistry";
import styles from "./AigcGuidePanel.module.less";

export function LegacyAigcGuidePanel({
  taskId,
  task,
  operation,
  activeCanvasId,
  stepCompletion,
  onSubmit,
  onReturnToChat,
}: {
  taskId: string;
  task: BoundAigcTask;
  operation: AigcOperationContract;
  activeCanvasId?: string | null;
  stepCompletion: Record<string, boolean>;
  onSubmit?: () => Promise<boolean>;
  onReturnToChat?: () => Promise<void> | void;
}) {
  const storageKey = `dclaw:aigc-guide:${taskId}:step`;
  const [stepIndex, setStepIndex] = useState(() =>
    Math.max(0, Number(localStorage.getItem(storageKey) || 0) || 0),
  );
  const [paused, setPaused] = useState(false);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const safeIndex = Math.min(
    stepIndex,
    Math.max(0, operation.human_guide.length - 1),
  );
  const step = operation.human_guide[safeIndex];
  const [controlAvailable, setControlAvailable] = useState(false);
  const wrongCanvas = Boolean(
    activeCanvasId && task.binding.canvas_id !== activeCanvasId,
  );
  const revisionFeedback =
    task.latest_review?.decision === "REVISION_REQUIRED"
      ? task.latest_review.assessment.trim()
      : "";

  useEffect(
    () => localStorage.setItem(storageKey, String(stepIndex)),
    [stepIndex, storageKey],
  );
  useEffect(() => {
    if (!step) return;
    const refresh = () =>
      setControlAvailable(Boolean(resolveControl(step.control_id)));
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [step, activeCanvasId]);
  if (!step) return null;
  const complete = stepCompletion[step.step_id] === true;
  const finalStep = safeIndex === operation.human_guide.length - 1;

  const submitAndReturn = () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError("");
    void (async () => {
      try {
        if ((await onSubmit?.()) !== true) {
          setError("尚未完成提交，请确认绑定节点已有成品后再试。");
          return;
        }
        try {
          await onReturnToChat?.();
        } catch {
          setError("素材任务已完成，但暂时无法返回会话。请点击返回任务会话重试。");
        }
      } catch (error) {
        setError(
          error instanceof Error && error.message
            ? error.message
            : "完成操作未能成功，素材和制作进度已保留，请重试。",
        );
      } finally {
        inFlight.current = false;
        setPending(false);
      }
    })();
  };

  return (
    <aside className={styles.panel} aria-label="旧版 AIGC 执行向导">
      <div
        className={styles.panelContent}
        role="region"
        aria-label="向导内容"
        tabIndex={0}
      >
        <header>
          <span>当前操作向导</span>
          <strong>{operation.title}</strong>
          <small>
            {safeIndex + 1} / {operation.human_guide.length}
          </small>
        </header>
        {revisionFeedback ? (
          <section className={styles.reviewFeedback} aria-label="上次审核意见">
            <h3>上次审核意见</h3>
            <p>{revisionFeedback}</p>
          </section>
        ) : null}
        <section className={styles.currentStep} aria-label="当前步骤">
          <div className={styles.stepEyebrow}>
            <span>现在只做这一步</span>
          </div>
          <h2>{step.title}</h2>
          <p>{step.instruction}</p>
          {!controlAvailable || wrongCanvas ? (
            <div className={styles.blocked}>
              {wrongCanvas ? "当前画布不属于此任务。" : step.recovery}
            </div>
          ) : null}
          <button
            type="button"
            disabled={!controlAvailable || wrongCanvas || paused}
            onClick={() => focusPlatformControl(step.control_id)}
          >
            <LocateFixed size={14} />
            定位当前控件
          </button>
        </section>
        {error ? <p role="alert">{error}</p> : null}
      </div>
      <footer aria-label="向导操作">
        <button
          type="button"
          disabled={pending || !onReturnToChat}
          onClick={() => {
            if (inFlight.current) return;
            inFlight.current = true;
            setPending(true);
            void Promise.resolve()
              .then(() => onReturnToChat?.())
              .catch(() =>
                setError("暂时无法返回任务会话，制作进度已保留，请重试。"),
              )
              .finally(() => {
                inFlight.current = false;
                setPending(false);
              });
          }}
        >
          <ArrowLeft size={14} />
          返回任务会话
        </button>
        {task.status === "SUBMITTED" ? (
          <button
            type="button"
            disabled={pending || wrongCanvas || !onSubmit || !onReturnToChat}
            onClick={submitAndReturn}
          >
            <RotateCcw size={14} />
            {pending ? "正在提交…" : "完成并返回会话"}
          </button>
        ) : task.status !== "ACCEPTED" ? (
          <>
            <button type="button" onClick={() => setPaused((value) => !value)}>
              {paused ? <Play size={14} /> : <Pause size={14} />}
              {paused ? "继续向导" : "暂停向导"}
            </button>
            <button
              type="button"
              data-guide-submit={finalStep || undefined}
              disabled={
                paused ||
                pending ||
                wrongCanvas ||
                !complete ||
                (finalStep && (!onSubmit || !onReturnToChat))
              }
              onClick={() => {
                if (!finalStep) return setStepIndex((value) => value + 1);
                submitAndReturn();
              }}
            >
              <Check size={14} />
              {finalStep
                ? pending
                  ? "正在提交…"
                  : "完成并返回会话"
                : "本步已完成"}
            </button>
          </>
        ) : null}
      </footer>
    </aside>
  );
}
