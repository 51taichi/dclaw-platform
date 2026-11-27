import type { MobileDisplayStatus, MobileTaskSummary } from "../../services/mobile";

const STATUS_LABELS: Record<MobileDisplayStatus, string> = {
  running: "执行中",
  pending_confirmation: "待确认",
  completed: "已完成",
  failed: "失败",
  idle: "未开始",
};

function normalizeSearchText(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

function taskSearchText(task: MobileTaskSummary): string {
  return [
    task.name,
    task.id,
    task.session_id,
    task.display_status,
    STATUS_LABELS[task.display_status],
    task.task_status,
    task.runtime_status,
  ]
    .map(normalizeSearchText)
    .filter(Boolean)
    .join(" ");
}

export function filterTasksByKeyword(
  tasks: MobileTaskSummary[],
  keyword: string,
): MobileTaskSummary[] {
  const normalizedKeyword = normalizeSearchText(keyword);
  if (!normalizedKeyword) {
    return tasks;
  }
  return tasks.filter((task) => taskSearchText(task).includes(normalizedKeyword));
}
