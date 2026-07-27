import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatSessionInitializer from ".";

const { mockSetCurrentSessionId, state } = vi.hoisted(() => ({
  mockSetCurrentSessionId: vi.fn(),
  state: {
    currentSessionId: undefined as string | undefined,
  },
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: () => ({
    currentSessionId: state.currentSessionId,
    setCurrentSessionId: mockSetCurrentSessionId,
  }),
}));

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <ChatSessionInitializer />
    </MemoryRouter>,
  );
}

describe("ChatSessionInitializer", () => {
  beforeEach(() => {
    state.currentSessionId = undefined;
    mockSetCurrentSessionId.mockReset();
  });

  it("clears stale session state on the /claw draft root", async () => {
    state.currentSessionId = "claw-global-session";

    renderAt("/claw");

    await waitFor(() => {
      expect(mockSetCurrentSessionId).toHaveBeenCalledWith(undefined);
    });
  });

  it("uses real chat ids from /claw detail routes", async () => {
    renderAt("/claw/real-chat-id");

    await waitFor(() => {
      expect(mockSetCurrentSessionId).toHaveBeenCalledWith("real-chat-id");
    });
  });
});
