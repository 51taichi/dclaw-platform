import { describe, expect, it } from "vitest";
import { isTaskGenerating } from "./taskListState";
import type { TaskListChat } from "./taskListFilters";

const taskWithStatus = (
  status: string,
  taskStatus?: string,
): TaskListChat =>
  ({ id: "task-id", status, task_status: taskStatus }) as TaskListChat;

describe("isTaskGenerating", () => {
  it("detects running task list items", () => {
    expect(isTaskGenerating(taskWithStatus("running"))).toBe(true);
    expect(isTaskGenerating(taskWithStatus("generating"))).toBe(true);
    expect(isTaskGenerating(taskWithStatus("idle", "running"))).toBe(true);
  });

  it("does not animate idle or completed task list items", () => {
    expect(isTaskGenerating(taskWithStatus("idle"))).toBe(false);
    expect(isTaskGenerating(taskWithStatus("completed"))).toBe(false);
  });
});
