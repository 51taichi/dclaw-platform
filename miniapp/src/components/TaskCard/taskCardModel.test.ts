import { describe, expect, it } from "vitest";

import type { MobileTaskSummary } from "../../services/mobile";
import { taskCardMeta } from "./taskCardModel";

function task(
  overrides: Partial<MobileTaskSummary> = {},
): MobileTaskSummary {
  return {
    id: "task-1",
    session_id: "session-1",
    name: "测试任务",
    display_status: "idle",
    pending_confirmation_count: 0,
    artifact_count: 0,
    ...overrides,
  };
}

describe("task card status copy", () => {
  it("does not label a completed task as waiting for artifacts", () => {
    expect(taskCardMeta(task({ display_status: "completed" }))).toBe(
      "结果已生成",
    );
  });

  it("shows the artifact count when the list endpoint has caught up", () => {
    expect(
      taskCardMeta(task({ display_status: "completed", artifact_count: 1 })),
    ).toBe("1 个产物");
  });

  it("keeps actionable copy for non-completed states", () => {
    expect(taskCardMeta(task({ display_status: "running" }))).toBe(
      "DClaw 正在执行",
    );
    expect(taskCardMeta(task({ display_status: "pending_confirmation" }))).toBe(
      "等待确认",
    );
    expect(taskCardMeta(task({ display_status: "failed" }))).toBe("执行失败");
    expect(taskCardMeta(task())).toBe("等待执行");
  });
});

