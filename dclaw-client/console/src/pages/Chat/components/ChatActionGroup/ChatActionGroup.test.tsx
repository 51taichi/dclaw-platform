import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

vi.mock("../ChatSearchPanel", () => ({ default: () => null }));
vi.mock("../ChatSessionDrawer", () => ({ default: () => null }));
vi.mock("../../sessionApi", () => ({
  default: { startDraftSession: vi.fn() },
}));
vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: () => ({
    setCurrentSessionId: vi.fn(),
  }),
}));

import ChatActionGroup from "./index";

describe("ChatActionGroup", () => {
  it("renders without crash", () => {
    expect(() => renderWithProviders(<ChatActionGroup />)).not.toThrow();
  });

  it("renders history icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkHistoryLine"]'),
    ).toBeInTheDocument();
  });

  it("renders new chat icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkNewChatFill"]'),
    ).toBeInTheDocument();
  });
});
