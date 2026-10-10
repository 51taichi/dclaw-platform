import { useRef, useState } from "react";
import {
  CircleCheck,
  ExternalLink,
  RotateCcw,
  Trash2,
  Video,
} from "lucide-react";
import { buildAigcTaskRoute } from "../routeSession";
import styles from "./SuperExpertAigcTaskCard.module.less";
import type { RuntimeEvent } from "../../../api/modules/runtimeEvents";

export type SuperExpertAigcTaskStatus =
  | "WAITING_TO_START"
  | "IN_PROGRESS"
  | "PAUSED"
  | "SUBMITTED"
  | "REVISION_REQUIRED"
  | "ACCEPTED"
  | "CANCELLED"
  | "INVALIDATED";

export interface SuperExpertAigcTaskCardProjection {
  cardId: string;
  materialTaskId: string;
  title: string;
  instruction?: string;
  status: SuperExpertAigcTaskStatus;
  binding?: Record<string, unknown>;
  installationId?: string;
}

const EVENT_STATUS: Record<string, SuperExpertAigcTaskStatus | undefined> = {
  "aigc.task.created": "WAITING_TO_START",
  "aigc.task.resumed": "IN_PROGRESS",
  "aigc.task.cancelled": "CANCELLED",
  "aigc.asset.submitted": "SUBMITTED",
};

export function projectSuperExpertAigcCards(
  events: RuntimeEvent[],
): SuperExpertAigcTaskCardProjection[] {
  const cards = new Map<string, SuperExpertAigcTaskCardProjection>();
  for (const runtimeEvent of events) {
    if (runtimeEvent.type !== "super_expert_event") continue;
    const envelope = runtimeEvent.payload?.envelope;
    if (!envelope || typeof envelope !== "object") continue;
    const item = envelope as Record<string, unknown>;
    const materialTaskId = String(item.material_task_id || "");
    const eventType = String(item.event_type || "");
    if (!materialTaskId) continue;
    const payload =
      item.payload && typeof item.payload === "object"
        ? (item.payload as Record<string, unknown>)
        : {};
    const previous = cards.get(materialTaskId);
    const status =
      (runtimeEvent.status as SuperExpertAigcTaskStatus | undefined) ||
      EVENT_STATUS[eventType] ||
      previous?.status;
    if (!status) continue;
    cards.set(materialTaskId, {
      cardId: String(payload.card_id || previous?.cardId || materialTaskId),
      materialTaskId,
      title: String(payload.title || previous?.title || "AIGC 素材制作任务"),
      instruction:
        typeof payload.instruction === "string"
          ? payload.instruction
          : previous?.instruction,
      status,
      installationId: String(
        item.installation_id || previous?.installationId || "",
      ),
      binding: {
        installation_id: item.installation_id,
        conversation_id: item.conversation_id,
        agent_task_id: item.agent_task_id,
        content_revision: item.content_revision,
        material_task_id: item.material_task_id,
        canvas_id: item.canvas_id,
        node_id: item.node_id,
      },
    });
  }
  return [...cards.values()];
}

const STATUS_LABELS: Record<SuperExpertAigcTaskStatus, string> = {
  WAITING_TO_START: "等待开始",
  IN_PROGRESS: "制作中",
  PAUSED: "已暂停",
  SUBMITTED: "待审核",
  REVISION_REQUIRED: "需要修改",
  ACCEPTED: "已审核",
  CANCELLED: "已取消",
  INVALIDATED: "已失效",
};

function actionLabel(status: SuperExpertAigcTaskStatus): string | null {
  if (status === "WAITING_TO_START") return "开始制作";
  if (status === "IN_PROGRESS" || status === "PAUSED") return "继续制作";
  if (status === "REVISION_REQUIRED") return "按意见修改";
  return null;
}

export function SuperExpertAigcTaskCard({
  projection,
  onCommand,
  compact = false,
  emphasized = false,
  onDelete,
}: {
  projection: SuperExpertAigcTaskCardProjection;
  onCommand: (command: "resume", materialTaskId: string) => Promise<void>;
  compact?: boolean;
  emphasized?: boolean;
  onDelete?: (materialTaskId: string) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const actionInFlight = useRef(false);
  const label = actionLabel(projection.status);
  const route = buildAigcTaskRoute(projection.materialTaskId);
  const instruction =
    projection.status === "ACCEPTED"
      ? "素材已通过审核，可查看成果并用于后续创作。"
      : projection.status === "SUBMITTED"
      ? "素材已提交，等待陆羽审核。"
      : projection.instruction;

  const act = async () => {
    if (actionInFlight.current) return;
    actionInFlight.current = true;
    setSubmitting(true);
    try {
      await onCommand("resume", projection.materialTaskId);
      setSubmitting(false);
    } catch (error) {
      actionInFlight.current = false;
      setSubmitting(false);
      throw error;
    }
  };

  if (compact) {
    const content = (
      <>
        <span className={styles.icon}>
          {projection.status === "ACCEPTED" ? (
            <CircleCheck size={16} />
          ) : (
            <Video size={16} />
          )}
        </span>
        <strong className={styles.compactTitle}>{projection.title}</strong>
        <span
          className={styles.status}
          role="status"
          data-status={projection.status}
        >
          {STATUS_LABELS[projection.status]}
        </span>
      </>
    );
    return (
      <section
        className={`${styles.card} ${styles.compact} ${
          emphasized ? styles.emphasized : ""
        }`}
        data-card-id={projection.cardId}
        data-task-status={projection.status}
      >
        {onDelete ? (
          <button
            type="button"
            className={styles.deleteButton}
            aria-label={`删除素材任务：${projection.title}`}
            title="删除素材任务"
            disabled={deleting}
            onClick={() => {
              setDeleting(true);
              void onDelete(projection.materialTaskId).catch(() =>
                setDeleting(false),
              );
            }}
          >
            <Trash2 size={14} />
          </button>
        ) : null}
        {label ? (
          <button
            type="button"
            className={styles.compactEntry}
            title={projection.title}
            aria-label={label}
            disabled={submitting}
            data-deep-link={route}
            onClick={() => void act()}
          >
            {content}
          </button>
        ) : (
          <a
            className={styles.compactEntry}
            title={projection.title}
            aria-label={
              projection.status === "ACCEPTED" ? "查看成果" : "查看详情"
            }
            href={route}
          >
            {content}
          </a>
        )}
      </section>
    );
  }

  return (
    <section
      className={`${styles.card} ${emphasized ? styles.emphasized : ""}`}
      data-card-id={projection.cardId}
      data-task-status={projection.status}
    >
      {onDelete ? (
        <button
          type="button"
          className={styles.deleteButton}
          aria-label={`删除素材任务：${projection.title}`}
          title="删除素材任务"
          disabled={deleting}
          onClick={() => {
            setDeleting(true);
            void onDelete(projection.materialTaskId).catch(() =>
              setDeleting(false),
            );
          }}
        >
          <Trash2 size={14} />
        </button>
      ) : null}
      <div className={styles.heading}>
        <span className={styles.icon}>
          {projection.status === "ACCEPTED" ? (
            <CircleCheck size={18} />
          ) : (
            <Video size={18} />
          )}
        </span>
        <div className={styles.titleBlock}>
          <strong title={projection.title}>{projection.title}</strong>
          <span
            className={styles.status}
            role="status"
            data-status={projection.status}
          >
            {STATUS_LABELS[projection.status]}
          </span>
        </div>
      </div>
      {instruction ? <p className={styles.instruction}>{instruction}</p> : null}
      <div className={styles.footer}>
        <span className={styles.kind}>AIGC 工作流</span>
        {label ? (
          <button
            type="button"
            className={styles.action}
            disabled={submitting}
            data-deep-link={route}
            onClick={() => void act()}
          >
            {projection.status === "REVISION_REQUIRED" ? (
              <RotateCcw size={15} />
            ) : (
              <ExternalLink size={15} />
            )}
            {label}
          </button>
        ) : (
          <a className={styles.resultLink} href={route}>
            {projection.status === "ACCEPTED" ? "查看成果" : "查看详情"}
            <ExternalLink size={14} />
          </a>
        )}
      </div>
    </section>
  );
}
