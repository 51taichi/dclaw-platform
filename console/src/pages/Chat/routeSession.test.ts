import { describe, expect, it } from "vitest";
import { getRouteChatId } from "./routeSession";

describe("getRouteChatId", () => {
  it("treats /claw as a draft root route, not a backend chat id", () => {
    expect(getRouteChatId("/claw")).toBeUndefined();
  });

  it("does not extract ids from the retired /chat route", () => {
    expect(getRouteChatId("/chat/chat-id")).toBeUndefined();
  });

  it("extracts real chat ids from task and claw detail routes", () => {
    expect(getRouteChatId("/task/task-id")).toBe("task-id");
    expect(getRouteChatId("/claw/claw-chat-id")).toBe("claw-chat-id");
  });

  it("decodes URL-encoded route chat ids", () => {
    expect(getRouteChatId("/claw/chat%20id")).toBe("chat id");
  });
});
