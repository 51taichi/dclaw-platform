import { beforeEach, describe, expect, it, vi } from "vitest";
import { superExpertPlatformApi } from "../../api/modules/superExpertPlatform";
import {
  getGuidedConversationRoute,
  submitGuidedTaskAsset,
} from "./guidedTaskActions";

vi.mock("../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: { command: vi.fn(), getConversationRoute: vi.fn() },
}));
const task = {
  status: "IN_PROGRESS",
  binding: {
    installation_id: "i1",
    conversation_id: "internal",
    material_task_id: "m1",
    canvas_id: "c1",
    node_id: "n1",
  },
};
describe("guided task actions", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
  });
  it("returns the owned public task route, not the internal session or old claw route", async () => {
    vi.mocked(superExpertPlatformApi.getConversationRoute).mockResolvedValue({
      conversation_id: "internal",
      chat_id: "public-chat",
      agent_id: "luyu",
    });
    expect(await getGuidedConversationRoute(task)).toBe("/task/public-chat");
  });
  it("does not invent a return route when the lookup binding differs", async () => {
    vi.mocked(superExpertPlatformApi.getConversationRoute).mockResolvedValue({
      conversation_id: "other",
      chat_id: "public-chat",
      agent_id: "luyu",
    });
    await expect(getGuidedConversationRoute(task)).rejects.toThrow();
  });
  it("does not submit when no output asset exists", async () => {
    await expect(submitGuidedTaskAsset(task, "")).rejects.toThrow();
    expect(superExpertPlatformApi.command).not.toHaveBeenCalled();
  });
  it("returns success only with a matching persisted submitted task and reuses idempotency on retry", async () => {
    vi.mocked(superExpertPlatformApi.command).mockResolvedValue({
      task: { ...task, status: "SUBMITTED", asset_id: "asset-1" },
    });
    expect(await submitGuidedTaskAsset(task, "asset-1")).toBe(true);
    expect(await submitGuidedTaskAsset(task, "asset-1")).toBe(true);
    const calls = vi.mocked(superExpertPlatformApi.command).mock.calls;
    expect(calls[0][0]).toBe("aigc.asset.submit");
    expect(calls[0][1].idempotency_key).toBe(calls[1][1].idempotency_key);
    expect(calls[0][1].arguments.asset_id).toBe("asset-1");
  });
  it.each(["wrong-task", "not-submitted", "wrong-asset"])(
    "rejects %s receipt",
    async (reason) => {
      vi.mocked(superExpertPlatformApi.command).mockResolvedValue({
        task: {
          ...task,
          status: reason === "not-submitted" ? "IN_PROGRESS" : "ACCEPTED",
          asset_id: reason === "wrong-asset" ? "asset-2" : "asset-1",
          binding: {
            ...task.binding,
            material_task_id: reason === "wrong-task" ? "m2" : "m1",
          },
        },
      });
      await expect(submitGuidedTaskAsset(task, "asset-1")).rejects.toThrow();
    },
  );
});
