import { describe, expect, it } from "vitest";
import { shouldRedirectAfterAgentChange } from "./agentRoutePolicy";

describe("shouldRedirectAfterAgentChange", () => {
  it("keeps an explicit task URL as the source of truth", () => {
    expect(
      shouldRedirectAfterAgentChange({
        previousAgent: "content_creation",
        nextAgent: "default",
        currentChatId: "clicked-task-id",
      }),
    ).toBe(false);
  });

  it("redirects to the next agent landing task only when no task is open", () => {
    expect(
      shouldRedirectAfterAgentChange({
        previousAgent: "content_creation",
        nextAgent: "default",
        currentChatId: undefined,
      }),
    ).toBe(true);
  });
});
