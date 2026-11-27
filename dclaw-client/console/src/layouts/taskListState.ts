import type { TaskListChat } from "./taskListFilters";

export function isTaskGenerating(task: TaskListChat): boolean {
  const status = String(task.status || "").toLowerCase();
  const taskStatus = String(task.task_status || "").toLowerCase();
  return (
    status === "running" ||
    status === "generating" ||
    taskStatus === "running" ||
    taskStatus === "generating"
  );
}
