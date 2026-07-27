import type { MobileTaskSummary } from "../../services/mobile";

export function taskCardMeta(task: MobileTaskSummary): string {
  if (task.display_status === "running") {
    return "DClaw 正在执行";
  }
  if (task.artifact_count > 0) {
    return `${task.artifact_count} 个产物`;
  }
  if (
    task.display_status === "completed" ||
    task.has_assistant_response === true
  ) {
    return "结果已生成";
  }
  if (task.display_status === "pending_confirmation") {
    return "等待确认";
  }
  if (task.display_status === "failed") {
    return "执行失败";
  }
  return "等待执行";
}

