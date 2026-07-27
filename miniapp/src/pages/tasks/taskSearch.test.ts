import { describe, expect, it } from "vitest";

import type { MobileTaskSummary } from "../../services/mobile";
import { filterTasksByKeyword } from "./taskSearch";

const baseTask: MobileTaskSummary = {
  id: "task-1",
  session_id: "session-1",
  name: "整理销售日报",
  display_status: "completed",
  runtime_status: "idle",
  task_status: "completed",
  pending_confirmation_count: 0,
  artifact_count: 0,
};

function task(
  patch: Partial<MobileTaskSummary> & Pick<MobileTaskSummary, "id" | "name">,
): MobileTaskSummary {
  return {
    ...baseTask,
    ...patch,
    session_id: patch.session_id ?? patch.id,
  };
}

describe("filterTasksByKeyword", () => {
  const tasks = [
    task({ id: "sales", name: "整理销售日报", display_status: "completed" }),
    task({ id: "contract", name: "合同风险检查", display_status: "running" }),
    task({
      id: "approval",
      name: "客户资料导出",
      display_status: "pending_confirmation",
    }),
  ];

  it("keeps all tasks when the query is empty", () => {
    expect(filterTasksByKeyword(tasks, "  ")).toEqual(tasks);
  });

  it("matches task names", () => {
    expect(filterTasksByKeyword(tasks, "合同").map((item) => item.id)).toEqual([
      "contract",
    ]);
  });

  it("matches Chinese task status labels", () => {
    expect(filterTasksByKeyword(tasks, "待确认").map((item) => item.id)).toEqual([
      "approval",
    ]);
  });
});
