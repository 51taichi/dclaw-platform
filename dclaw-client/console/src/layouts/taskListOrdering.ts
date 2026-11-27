import type { TaskListChat } from "./taskListFilters";

function timeValue(raw?: string | null): number {
  if (!raw) return 0;
  const value = new Date(raw).getTime();
  return Number.isFinite(value) ? value : 0;
}

export function sortTasksForSidebar(tasks: TaskListChat[]): TaskListChat[] {
  return [...tasks].sort((a, b) => {
    const createdDiff = timeValue(b.created_at) - timeValue(a.created_at);
    if (createdDiff !== 0) return createdDiff;

    const updatedDiff = timeValue(b.updated_at) - timeValue(a.updated_at);
    if (updatedDiff !== 0) return updatedDiff;

    return (b.id || "").localeCompare(a.id || "");
  });
}
