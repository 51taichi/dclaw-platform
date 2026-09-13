import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  LocateFixed,
  Pause,
  Play,
  Plus,
  RotateCcw,
  SkipForward,
  Workflow,
} from "lucide-react";

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

type DisplayParameter = {
  label: string;
  value: string;
};

type DisplayParameterGroup = {
  key: string;
  title: string;
  parameters: DisplayParameter[];
};

const PARAMETER_LABELS: Record<string, string> = {
  prompt: "提示词",
  text: "文本内容",
  aspect_ratio: "画面比例",
  resolution: "清晰度",
  duration_seconds: "时长",
  count: "生成数量",
  shot_count: "镜头数量",
  generate_audio: "生成音频",
  image_mode: "图片模式",
  video_mode: "视频模式",
  voice: "声音",
  language: "语言",
  script_mode: "脚本模式",
  provider_id: "模型提供商",
  model_id: "模型",
  capability: "生成能力",
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const displayValue = (key: string, value: unknown): string | null => {
  if (value === null || value === undefined || value === "") return null;
  if (key === "duration_seconds" && typeof value === "number") {
    return `${value} 秒`;
  }
  if (key === "count" && typeof value === "number") return `${value} 张`;
  if (key === "shot_count" && typeof value === "number") return `${value} 个`;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (["string", "number"].includes(typeof value)) return String(value);
  return null;
};

const collectParameters = (
  source: Record<string, unknown> | null,
): DisplayParameter[] =>
  Object.entries(source ?? {}).flatMap(([key, value]) => {
    const label = PARAMETER_LABELS[key];
    const formatted = label ? displayValue(key, value) : null;
    return label && formatted ? [{ label, value: formatted }] : [];
  });

function buildTaskParameterGroups(
  task: BoundAigcTask,
): DisplayParameterGroup[] {
  const workflow = asRecord(task.workflow);
  const blueprint = asRecord(workflow?.blueprint);
  const nodes = Array.isArray(blueprint?.nodes) ? blueprint.nodes : [];
  const workflowGroups = nodes.flatMap((candidate, index) => {
    const node = asRecord(candidate);
    if (!node) return [];
    const parameters = [
      ...collectParameters(asRecord(node.inputs)),
      ...collectParameters(asRecord(node.parameters)),
      ...collectParameters({
        provider_id: node.provider_id,
        model_id: node.model_id,
        capability: node.capability,
      }),
    ];
    if (!parameters.length) return [];
    return [
      {
        key: String(node.node_id ?? index),
        title: String(node.title ?? `节点 ${index + 1}`),
        parameters,
      },
    ];
  });
  if (workflowGroups.length) return workflowGroups;

  const operationParameters = collectParameters(
    asRecord(task.operation_arguments),
  );
  return operationParameters.length
    ? [
        {
          key: "operation",
          title: "任务参数",
          parameters: operationParameters,
        },
      ]
    : [];
}

export function AigcGuidePanel({
  task,
  guide,
  activeCanvasId,
  onFocusStep,
  onSkipOptional,
  onRefresh,
  onManualBuild,
  onSubmit,
  onReturnToChat,
}: {
  task: BoundAigcTask;
  guide: AigcGuideProjection;
  activeCanvasId?: string | null;
  onFocusStep?: (nodeId: string, controlId: string) => void;
  onSkipOptional?: (step: AigcGuideStepProjection) => Promise<void>;
  onRefresh?: () => Promise<unknown> | void;
  onManualBuild?: (step: AigcGuideStepProjection) => Promise<void>;
  onSubmit?: () => Promise<boolean>;
  onReturnToChat?: () => Promise<void> | void;
}) {
  const [paused, setPaused] = useState(false);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const [reviewReply, setReviewReply] = useState("");
  const current = guide.current_step;
  const steps = useMemo(() => {
    if (
      !current ||
      guide.steps.some((step) => step.step_id === current.step_id)
    ) {
      return guide.steps;
    }
    return [...guide.steps, current];
  }, [current, guide.steps]);
  const currentIndex = current
    ? Math.max(
        0,
        steps.findIndex((step) => step.step_id === current.step_id),
      )
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
  const parameterGroups = useMemo(() => buildTaskParameterGroups(task), [task]);

  const run = async (operation: () => Promise<unknown> | void) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      await operation();
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  const submitAndReturn = () => {
    setReviewReply("");
    void run(async () => {
      try {
        const submitted = await onSubmit?.();
        if (submitted !== true) {
          setReviewReply("尚未提交审核，请确认绑定节点已有成品后再试。");
          return;
        }
        try {
          await onReturnToChat?.();
        } catch {
          setReviewReply(
            "素材已提交，但暂时无法返回会话。请点击返回任务会话重试。",
          );
        }
      } catch {
        setReviewReply("提交未能完成，素材和制作进度已保留，请重试。");
      }
    });
  };

  return (
    <aside className={styles.panel} aria-label="AIGC 执行向导">
      <div
        className={styles.panelContent}
        role="region"
        aria-label="向导内容"
        tabIndex={0}
      >
        <header>
          <span>当前操作向导</span>
          <strong>{projectName || "AIGC 素材任务"}</strong>
          <small>
            {Math.min(currentIndex + 1, Math.max(steps.length, 1))} /{" "}
            {Math.max(steps.length, 1)}
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
              <em data-status={current.status}>
                {STATUS_LABELS[current.status]}
              </em>
            </div>
            <h2>{current.title}</h2>
            <p>{current.instruction}</p>
            {current.recovery ? (
              <div className={styles.recovery}>
                恢复方式：{current.recovery.action}（{current.recovery.code}）
              </div>
            ) : null}
            <div className={styles.currentActions}>
              {current.kind === "MANUAL_BUILD" && current.manual_action ? (
                <button
                  type="button"
                  data-platform-control-id={current.control_id ?? undefined}
                  disabled={
                    paused ||
                    pending ||
                    wrongCanvas ||
                    current.status !== "READY"
                  }
                  onClick={() => void run(() => onManualBuild?.(current))}
                >
                  {current.manual_action === "ADD_NODE" ? (
                    <Plus size={14} />
                  ) : (
                    <Workflow size={14} />
                  )}
                  {current.manual_action === "ADD_NODE"
                    ? "添加此节点"
                    : "连接这两个节点"}
                </button>
              ) : null}
              {current.kind !== "MANUAL_BUILD" &&
              current.kind !== "SUBMIT" &&
              current.node_id &&
              current.control_id ? (
                <button
                  type="button"
                  disabled={
                    paused || wrongCanvas || current.status === "LOCKED"
                  }
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
                  <SkipForward size={14} />
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

        {parameterGroups.length ? (
          <details className={styles.parameters}>
            <summary>查看任务参数</summary>
            <div className={styles.parameterGroups}>
              {parameterGroups.map((group) => (
                <section key={group.key} className={styles.parameterGroup}>
                  <h3>{group.title}</h3>
                  <dl>
                    {group.parameters.map((parameter) => (
                      <div key={`${parameter.label}:${parameter.value}`}>
                        <dt>{parameter.label}</dt>
                        <dd>{parameter.value}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ))}
            </div>
          </details>
        ) : null}

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
          <section role="alert" aria-label="提交提示">
            <h3>提交提示</h3>
            <p>{reviewReply}</p>
          </section>
        ) : null}
      </div>
      <footer aria-label="向导操作">
        <button
          type="button"
          disabled={pending || !onReturnToChat}
          onClick={() =>
            void run(async () => {
              try {
                await onReturnToChat?.();
              } catch {
                setReviewReply(
                  "暂时无法打开原任务会话，请重试；素材和制作进度已保留。",
                );
              }
            })
          }
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
            {pending ? "正在审核…" : "重新审核并返回会话"}
          </button>
        ) : task.status !== "ACCEPTED" ? (
          <>
            <button type="button" onClick={() => setPaused((value) => !value)}>
              {paused ? <Play size={14} /> : <Pause size={14} />}
              {paused ? "继续向导" : "暂停向导"}
            </button>
            {current?.kind === "SUBMIT" && current.status === "READY" ? (
              <button
                type="button"
                data-guide-submit="true"
                disabled={
                  paused ||
                  pending ||
                  wrongCanvas ||
                  !onSubmit ||
                  !onReturnToChat
                }
                onClick={submitAndReturn}
              >
                <Check size={14} />
                {pending ? "正在提交…" : "提交审核并返回会话"}
              </button>
            ) : null}
          </>
        ) : null}
      </footer>
    </aside>
  );
}
