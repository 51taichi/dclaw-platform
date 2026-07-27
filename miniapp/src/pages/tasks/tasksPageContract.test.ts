import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("tasks page contract", () => {
  it("polls running tasks and notifies when a result becomes available", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("TASKS_POLL_INTERVAL_MS");
    expect(source).toContain("runningTaskIdsRef");
    expect(source).toContain("setInterval");
    expect(source).toContain("clearInterval");
    expect(source).toContain("任务已完成，可查看结果");
    expect(source).toContain('task.display_status === "running"');
  });

  it("offers task detail, result, archive, and delete actions from the task queue", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("showTaskActions");
    expect(source).toContain("showActionSheet");
    expect(source).toContain("查看详情");
    expect(source).toContain("查看结果");
    expect(source).toContain("hasTaskResult(task)");
    expect(source).toContain("归档");
    expect(source).toContain("删除");
    expect(source).toContain("archiveTask");
    expect(source).toContain("deleteTask");
    expect(source).toContain("归档后 Web 端和小程序任务列表都不再显示");
    expect(source).toContain("/pages/result/index?chatId=");
  });

  it("shows a task search field and renders filtered task results", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("filterTasksByKeyword");
    expect(source).toContain("searchQuery");
    expect(source).toContain("placeholder=\"搜索任务名称或状态\"");
    expect(source).toContain("visibleTasks.map");
    expect(source).toContain("没有找到相关任务");
  });

});
