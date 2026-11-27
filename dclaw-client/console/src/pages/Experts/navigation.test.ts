import { describe, expect, it } from "vitest";
import { resolveExpertSummonTarget } from "./navigation";

describe("resolveExpertSummonTarget", () => {
  it("starts a fresh task when summoning an expert team from an existing task", () => {
    expect(
      resolveExpertSummonTarget({
        from: "/task/old-task-id",
        isTeam: true,
      }),
    ).toBe("/task");
  });

  it("keeps ordinary experts able to restore their last task", () => {
    expect(
      resolveExpertSummonTarget({
        from: "/task/current-task-id",
        isTeam: false,
        lastChatId: "last-agent-task-id",
      }),
    ).toBe("/task/last-agent-task-id");
  });

  it("normalizes retired chat routes to task routes", () => {
    expect(
      resolveExpertSummonTarget({
        from: "/chat/old-chat-id",
        isTeam: true,
      }),
    ).toBe("/task");
  });
});
