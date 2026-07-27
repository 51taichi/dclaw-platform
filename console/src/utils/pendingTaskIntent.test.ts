import { afterEach, describe, expect, it } from "vitest";
import {
  clearPendingTaskIntent,
  loadPendingTaskIntent,
  savePendingTaskIntent,
} from "./pendingTaskIntent";

describe("pendingTaskIntent", () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it("persists and clears the first task intent by chat id", () => {
    savePendingTaskIntent("chat-1", {
      prompt: "生成一份方案",
      agentId: "default",
      expertTeam: null,
    });

    expect(loadPendingTaskIntent("chat-1")).toEqual({
      prompt: "生成一份方案",
      agentId: "default",
      expertTeam: null,
    });

    clearPendingTaskIntent("chat-1");

    expect(loadPendingTaskIntent("chat-1")).toBeNull();
  });

  it("ignores malformed stored intents", () => {
    sessionStorage.setItem("qwenpaw_pending_task_intent_chat-1", "{bad json");

    expect(loadPendingTaskIntent("chat-1")).toBeNull();
  });
});
