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
  const [stepIndex, setStepIndex] = useState(() => {
    const persisted = Number(localStorage.getItem(storageKey) || 0);
    return Number.isFinite(persisted) && persisted >= 0
      ? Math.floor(persisted)
      : 0;
  });
  const [paused, setPaused] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewReply, setReviewReply] = useState("");
  const safeStepIndex = Math.min(
    stepIndex,
    Math.max(0, operation.human_guide.length - 1),
  );
  const step = operation.human_guide[safeStepIndex];
  const [controlAvailable, setControlAvailable] = useState(false);
  const wrongCanvas = Boolean(
    activeCanvasId && task.binding.canvas_id !== activeCanvasId,
  );

  useEffect(() => {
    localStorage.setItem(storageKey, String(stepIndex));
  }, [stepIndex, storageKey]);

  useEffect(() => {
    if (!step) return;
    const refresh = () =>
      setControlAvailable(Boolean(resolveControl(step.control_id)));
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [step, activeCanvasId]);

  useEffect(() => {
    if (!step || wrongCanvas || paused || !controlAvailable) return;
    focusPlatformControl(step.control_id);
  }, [controlAvailable, paused, step, wrongCanvas]);

  if (!step) return null;
  const finalStep = safeStepIndex >= operation.human_guide.length - 1;
  const currentStepComplete = stepCompletion[step.step_id] === true;
  const taskArguments = task.operation_arguments ?? {};
  const projectName = String(taskArguments.project_name ?? "").trim();
  const prompt = String(taskArguments.prompt ?? "").trim();
  const modelId = String(taskArguments.model_id ?? "").trim();
  const aspectRatio = String(taskArguments.aspect_ratio ?? "").trim();
  const durationSeconds = Number(taskArguments.duration_seconds);

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
      <section aria-label="本任务制作参数">
        <h3>本任务制作参数</h3>
        {projectName ? <p>{projectName}</p> : null}
        {prompt ? <p>{prompt}</p> : null}
        {modelId ? (
          <p>{modelId === "auto" ? "模型：请选择一个可用模型" : `模型：${modelId}`}</p>
        ) : null}
        {aspectRatio && Number.isFinite(durationSeconds) ? (
          <p>{aspectRatio} · {durationSeconds} 秒</p>
        ) : null}
        {prompt ? (
          <button
            type="button"
            onClick={() => void navigator.clipboard.writeText(prompt)}
          >
            <Copy size={14} />
            复制提示词
          </button>
        ) : null}
      </section>
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
      {!currentStepComplete ? (
        <div className={styles.blocked}>
          尚未检测到完成标志，完成当前页面操作后才能进入下一步。
        </div>
      ) : null}
      {reviewReply ? (
        <section aria-label="专家审核结果">
          <h3>专家审核结果</h3>
          <p>{reviewReply}</p>
        </section>
      ) : null}
      <footer>
        {task.status === "ACCEPTED" ? (
          <button type="button" onClick={onReturnToChat}>
            返回原会话
          </button>
        ) : (
          <>
            <button type="button" onClick={() => setPaused((value) => !value)}>
              {paused ? <Play size={14} /> : <Pause size={14} />}
              {paused ? "继续向导" : "暂停向导"}
            </button>
            <button
              type="button"
              disabled={
                paused ||
                reviewing ||
                !controlAvailable ||
                wrongCanvas ||
                !currentStepComplete
              }
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
          </>
        )}
      </footer>
    </aside>
  );
}
