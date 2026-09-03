import { useMemo, useState } from "react";
import { LocateFixed, Pause, Play, RotateCcw } from "lucide-react";

import type {
  AigcGuideProjection,
  AigcGuideStepProjection,
  BoundAigcTask,
} from "../../../../api/modules/superExpertPlatform";
import styles from "./AigcGuidePanel.module.less";

const STATUS_LABELS: Record<AigcGuideStepProjection["status"], string> = {
  LOCKED: "等待前一步",
  READY: "可以操作",
  RUNNING: "生成中",
  FAILED: "需要重试",
  COMPLETED: "已完成",
  SKIPPED: "已跳过",
  BLOCKED: "已阻断",
};

export function AigcGuidePanel({
  task,
  guide,
  activeCanvasId,
  onFocusStep,
  onSkipOptional,
  onRefresh,
  onSubmit,
  onReturnToChat,
}: {
  task: BoundAigcTask;
  guide: AigcGuideProjection;
  activeCanvasId?: string | null;
  onFocusStep?: (nodeId: string, controlId: string) => void;
  onSkipOptional?: (step: AigcGuideStepProjection) => Promise<void>;
  onRefresh?: () => Promise<unknown> | void;
  onSubmit?: () => Promise<string | void>;
  onReturnToChat?: () => void;
}) {
  const [paused, setPaused] = useState(false);
  const [pending, setPending] = useState(false);
  const [reviewReply, setReviewReply] = useState("");
  const current = guide.current_step;
  const steps = useMemo(() => {
    if (!current || guide.steps.some((step) => step.step_id === current.step_id)) {
      return guide.steps;
    }
    return [...guide.steps, current];
  }, [current, guide.steps]);
  const currentIndex = current
    ? Math.max(0, steps.findIndex((step) => step.step_id === current.step_id))
    : Math.max(0, steps.length - 1);
  const completed = steps.filter((step) =>
    ["COMPLETED", "SKIPPED"].includes(step.status),
  );
  const next = current
    ? steps.slice(currentIndex + 1).find((step) => step.status === "LOCKED")
    : undefined;
  const wrongCanvas = Boolean(
    activeCanvasId && task.binding.canvas_id !== activeCanvasId,
  );
  const taskArguments = task.operation_arguments ?? {};
  const projectName = String(taskArguments.project_name ?? "").trim();
  const prompt = String(taskArguments.prompt ?? "").trim();
  const aspectRatio = String(taskArguments.aspect_ratio ?? "").trim();
  const durationSeconds = Number(taskArguments.duration_seconds);

  const run = async (operation: () => Promise<unknown> | void) => {
    if (pending) return;
    setPending(true);
    try {
      await operation();
    } finally {
      setPending(false);
    }
  };

  return (
    <aside className={styles.panel} aria-label="AIGC 执行向导">
      <header>
        <span>当前操作向导</span>
        <strong>{projectName || "AIGC 素材任务"}</strong>
        <small>
          {Math.min(currentIndex + 1, Math.max(steps.length, 1))} / {Math.max(steps.length, 1)}
        </small>
      </header>

      {wrongCanvas ? (
        <div className={styles.blocked}>
          当前画布不属于此任务。请返回任务绑定画布，其他画布不会推进向导。
        </div>
      ) : null}

      {current ? (
        <section className={styles.currentStep} aria-label="当前步骤">
          <div className={styles.stepEyebrow}>
            <span>现在只做这一步</span>
            <em data-status={current.status}>{STATUS_LABELS[current.status]}</em>
          </div>
          <h2>{current.title}</h2>
          <p>{current.instruction}</p>
          {current.recovery ? (
            <div className={styles.recovery}>
              恢复方式：{current.recovery.action}（{current.recovery.code}）
            </div>
          ) : null}
          <div className={styles.currentActions}>
            {current.node_id && current.control_id ? (
              <button
                type="button"
                disabled={paused || wrongCanvas || current.status === "LOCKED"}
                onClick={() =>
                  onFocusStep?.(current.node_id!, current.control_id!)
                }
              >
                <LocateFixed size={14} />
                {current.kind === "GENERATE"
                  ? "定位到生成按钮"
                  : "定位当前控件"}
              </button>
            ) : null}
            {current.optional && current.status !== "COMPLETED" ? (
              <button
                type="button"
                disabled={paused || pending || wrongCanvas}
                onClick={() => void run(() => onSkipOptional?.(current))}
              >
                跳过这个可选步骤
              </button>
            ) : null}
            {current.status === "FAILED" && onRefresh ? (
              <button
                type="button"
                disabled={pending}
                onClick={() => void run(onRefresh)}
              >
                <RotateCcw size={14} />
                刷新任务状态
              </button>
            ) : null}
          </div>
        </section>
      ) : (
        <section className={styles.currentStep}>
          <h2>全部步骤已完成</h2>
          <p>当前任务没有待执行步骤。</p>
        </section>
      )}

      <details className={styles.parameters}>
        <summary>查看任务参数</summary>
        {projectName ? <p>{projectName}</p> : null}
        {prompt ? <p>{prompt}</p> : null}
        {aspectRatio && Number.isFinite(durationSeconds) ? (
          <p>{aspectRatio} · {durationSeconds} 秒</p>
        ) : null}
      </details>

      {completed.length ? (
        <section className={styles.completedSteps} aria-label="已完成步骤">
          <h3>已完成</h3>
          <ul>
            {completed.map((step) => (
              <li key={step.step_id}>{step.title}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {next ? (
        <section className={styles.nextStep} aria-label="下一步预告">
          <span>下一步</span>
          <strong>{next.title}</strong>
        </section>
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
            {current?.kind === "SUBMIT" && current.status === "READY" ? (
              <button
                type="button"
                disabled={paused || pending || wrongCanvas}
                onClick={() => {
                  setReviewReply("");
                  void run(async () => {
                    try {
                      const reply = await onSubmit?.();
                      if (reply) setReviewReply(reply);
                    } catch {
                      setReviewReply(
                        "本次审核未能安全完成，任务进度已保留，请稍后再次提交。",
                      );
                    }
                  });
                }}
              >
                {pending ? "专家审核中…" : "提交给专家审核"}
              </button>
            ) : null}
          </>
        )}
      </footer>
    </aside>
  );
}
