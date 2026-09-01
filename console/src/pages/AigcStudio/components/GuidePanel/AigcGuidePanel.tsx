import { useEffect, useState } from "react";
import { Check, Copy, LocateFixed, Pause, Play } from "lucide-react";
import type {
  AigcOperationContract,
  BoundAigcTask,
} from "../../../../api/modules/superExpertPlatform";
import { focusPlatformControl, resolveControl } from "./controlRegistry";
import styles from "./AigcGuidePanel.module.less";

export function AigcGuidePanel({
  taskId,
  task,
  operation,
  activeCanvasId,
  onSubmit,
}: {
  taskId: string;
  task: BoundAigcTask;
  operation: AigcOperationContract;
  activeCanvasId?: string | null;
  onSubmit?: () => Promise<string | void>;
}) {
  const storageKey = `dclaw:aigc-guide:${taskId}:step`;
  const [stepIndex, setStepIndex] = useState(() =>
    Math.max(0, Number(localStorage.getItem(storageKey) || 0)),
  );
  const [paused, setPaused] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewReply, setReviewReply] = useState("");
  const step =
    operation.human_guide[
      Math.min(stepIndex, operation.human_guide.length - 1)
    ];
  const [controlAvailable, setControlAvailable] = useState(false);
  const wrongCanvas = Boolean(
    activeCanvasId && task.binding.canvas_id !== activeCanvasId,
  );

  useEffect(() => {
    localStorage.setItem(storageKey, String(stepIndex));
  }, [stepIndex, storageKey]);

  useEffect(() => {
    const refresh = () =>
      setControlAvailable(Boolean(resolveControl(step.control_id)));
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [step.control_id, activeCanvasId]);

  if (!step) return null;
  const finalStep = stepIndex >= operation.human_guide.length - 1;

  return (
    <aside className={styles.panel} aria-label="AIGC 任务操作助手">
      <header>
        <span>真人操作向导</span>
        <strong>{operation.title}</strong>
        <small>
          {stepIndex + 1} / {operation.human_guide.length}
        </small>
      </header>
      {wrongCanvas ? (
        <div className={styles.blocked}>
          当前画布不属于此任务。请返回绑定画布，其他画布的操作不会推进任务。
        </div>
      ) : null}
      {!controlAvailable ? (
        <div className={styles.blocked}>
          当前步骤所需控件不可用，向导已停止推进。请按下方恢复说明处理。
        </div>
      ) : null}
      <section>
        <h3>{step.title}</h3>
        <p>{step.instruction}</p>
        <button
          type="button"
          onClick={() => void navigator.clipboard.writeText(step.instruction)}
        >
          <Copy size={14} />
          复制本步说明
        </button>
        <button
          type="button"
          disabled={!controlAvailable || wrongCanvas}
          onClick={() => focusPlatformControl(step.control_id)}
        >
          <LocateFixed size={14} />
          定位当前控件
        </button>
      </section>
      <dl>
        <dt>完成标志</dt>
        <dd>{step.success_signal}</dd>
        <dt>遇到问题</dt>
        <dd>{step.recovery}</dd>
      </dl>
      {reviewReply ? (
        <section aria-label="专家审核结果">
          <h3>专家审核结果</h3>
          <p>{reviewReply}</p>
        </section>
      ) : null}
      <footer>
        <button type="button" onClick={() => setPaused((value) => !value)}>
          {paused ? <Play size={14} /> : <Pause size={14} />}
          {paused ? "继续向导" : "暂停向导"}
        </button>
        <button
          type="button"
          disabled={paused || reviewing || !controlAvailable || wrongCanvas}
          onClick={() => {
            if (finalStep) {
              setReviewing(true);
              setReviewReply("");
              void (async () => {
                try {
                  const reply = await onSubmit?.();
                  if (reply) setReviewReply(reply);
                } catch {
                  setReviewReply(
                    "本次审核未能安全完成，任务进度已保留，请稍后再次提交。",
                  );
                } finally {
                  setReviewing(false);
                }
              })();
            } else setStepIndex((value) => value + 1);
          }}
        >
          <Check size={14} />
          {finalStep
            ? reviewing
              ? "专家审核中…"
              : "提交给专家审核"
            : "本步已完成"}
        </button>
      </footer>
    </aside>
  );
}
