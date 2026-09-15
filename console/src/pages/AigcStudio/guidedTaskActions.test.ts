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
  version: 2,
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

  it("uses a new submission identity after a revision cycle changes the task version", async () => {
    vi.mocked(superExpertPlatformApi.command)
      .mockResolvedValueOnce({
        task: {
          ...task,
          status: "REVISION_REQUIRED",
          asset_id: "asset-1",
        },
      })
      .mockResolvedValueOnce({
        task: {
          ...task,
          version: 6,
          status: "REVISION_REQUIRED",
          asset_id: "asset-1",
        },
      });

    await submitGuidedTaskAsset(task, "asset-1");
    await submitGuidedTaskAsset({ ...task, version: 6 }, "asset-1");

    const calls = vi.mocked(superExpertPlatformApi.command).mock.calls;
    expect(calls[0][1].idempotency_key).not.toBe(calls[1][1].idempotency_key);
  });
  it("reuses the original submission identity when retrying an incomplete review", async () => {
    vi.mocked(superExpertPlatformApi.command)
      .mockResolvedValueOnce({
        task: { ...task, status: "SUBMITTED", version: 3, asset_id: "asset-1" },
      })
      .mockResolvedValueOnce({
        task: { ...task, status: "ACCEPTED", version: 4, asset_id: "asset-1" },
      });

    await submitGuidedTaskAsset(task, "asset-1");
    await submitGuidedTaskAsset(
      { ...task, status: "SUBMITTED", version: 3 },
      "asset-1",
    );

    const calls = vi.mocked(superExpertPlatformApi.command).mock.calls;
    expect(calls[0][1].idempotency_key).toBe(calls[1][1].idempotency_key);
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
    expect(await submitGuidedTaskAsset(task, "asset-1")).toEqual({
      submitted: true,
      agentReview: undefined,
    });
    expect(await submitGuidedTaskAsset(task, "asset-1")).toEqual({
      submitted: true,
      agentReview: undefined,
    });
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

it("returns a nonterminal review explanation without treating submission as lost", async () => {
  vi.mocked(superExpertPlatformApi.command).mockResolvedValue({
    task: { ...task, status: "SUBMITTED", asset_id: "asset-1" },
    agent_review: {
      status: "model_required",
      reply: "需要支持图片识别的模型。",
      required_modalities: ["image"],
    },
  });

  expect(await submitGuidedTaskAsset(task, "asset-1")).toEqual({
    submitted: true,
    agentReview: {
      status: "model_required",
      reply: "需要支持图片识别的模型。",
      required_modalities: ["image"],
    },
  });
});

it("sends the complete bundle and changes submission identity when any asset changes", async () => {
  const entries = [
    { node_id: "copy", asset_id: "copy-1" },
    { node_id: "image", asset_id: "image-1" },
  ];
  const command = vi.mocked(superExpertPlatformApi.command);
  command.mockClear();
  command.mockResolvedValue({
    task: {
      ...task,
      status: "SUBMITTED",
      asset_id: "copy-1",
      review_assets: entries,
    },
  });
  await submitGuidedTaskAsset(task, "copy-1", entries);
  expect(command.mock.calls[0][1].arguments.review_assets).toEqual(entries);
  const changed = [entries[0], { node_id: "image", asset_id: "image-2" }];
  command.mockResolvedValue({
    task: {
      ...task,
      status: "SUBMITTED",
      asset_id: "copy-1",
      review_assets: changed,
    },
  });
  await submitGuidedTaskAsset(task, "copy-1", changed);
  expect(command.mock.calls[0][1].idempotency_key).not.toBe(
    command.mock.calls[1][1].idempotency_key,
  );
});
