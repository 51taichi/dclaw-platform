import { describe, expect, it } from "vitest";
import { buildAutoRoutingModelSlotRequest } from "./chatToolbarModelSelection";

describe("buildAutoRoutingModelSlotRequest", () => {
  it("builds an agent-scoped Auto routing request before a chat exists", () => {
    expect(
      buildAutoRoutingModelSlotRequest({
        selectedAgent: "default",
      }),
    ).toEqual({
      provider_id: "auto",
      model: "routing",
      scope: "agent",
      agent_id: "default",
    });
  });

  it("builds a chat-scoped Auto routing request inside an existing task", () => {
    expect(
      buildAutoRoutingModelSlotRequest({
        selectedAgent: "default",
        chatId: "chat-123",
      }),
    ).toEqual({
      provider_id: "auto",
      model: "routing",
      scope: "chat",
      agent_id: "default",
      chat_id: "chat-123",
    });
  });
});
