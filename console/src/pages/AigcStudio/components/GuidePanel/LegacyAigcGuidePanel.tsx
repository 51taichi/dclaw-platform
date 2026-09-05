import { useEffect, useState } from "react";
import { Check, LocateFixed, Pause, Play } from "lucide-react";

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
  onSubmit?: () => Promise<string | void>;
  onReturnToChat?: () => void;
}) {
  const storageKey = `dclaw:aigc-guide:${taskId}:step`;
  const [stepIndex, setStepIndex] = useState(() =>
    Math.max(0, Number(localStorage.getItem(storageKey) || 0) || 0),
  );
  const [paused, setPaused] = useState(false);
  const [pending, setPending] = useState(false);
  const safeIndex = Math.min(stepIndex, Math.max(0, operation.human_guide.length - 1));
  const step = operation.human_guide[safeIndex];
  const [controlAvailable, setControlAvailable] = useState(false);
  const wrongCanvas = Boolean(activeCanvasId && task.binding.canvas_id !== activeCanvasId);

  useEffect(() => localStorage.setItem(storageKey, String(stepIndex)), [stepIndex, storageKey]);
  useEffect(() => {
    if (!step) return;
    const refresh = () => setControlAvailable(Boolean(resolveControl(step.control_id)));
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [step, activeCanvasId]);
  if (!step) return null;
  const complete = stepCompletion[step.step_id] === true;
  const finalStep = safeIndex === operation.human_guide.length - 1;

  return (
    <aside className={styles.panel} aria-label="旧版 AIGC 执行向导">
      <header>
        <span>当前操作向导</span>
        <strong>{operation.title}</strong>
        <small>{safeIndex + 1} / {operation.human_guide.length}</small>
      </header>
      <section className={styles.currentStep} aria-label="当前步骤">
        <div className={styles.stepEyebrow}><span>现在只做这一步</span></div>
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
          <LocateFixed size={14} />定位当前控件
        </button>
      </section>
      <footer>
        {task.status === "ACCEPTED" ? (
          <button type="button" onClick={onReturnToChat}>返回原会话</button>
        ) : (
          <>
            <button type="button" onClick={() => setPaused((value) => !value)}>
              {paused ? <Play size={14} /> : <Pause size={14} />}
              {paused ? "继续向导" : "暂停向导"}
            </button>
            <button
              type="button"
              disabled={paused || pending || wrongCanvas || !complete}
              onClick={() => {
                if (!finalStep) return setStepIndex((value) => value + 1);
                setPending(true);
                void Promise.resolve(onSubmit?.()).finally(() => setPending(false));
              }}
            >
              <Check size={14} />
              {finalStep ? (pending ? "专家审核中…" : "提交给专家审核") : "本步已完成"}
            </button>
          </>
        )}
      </footer>
    </aside>
  );
}
