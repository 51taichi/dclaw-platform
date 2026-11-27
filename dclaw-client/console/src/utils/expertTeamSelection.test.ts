import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearExpertTeamSelectionForChat,
  loadExpertTeamSelectionForChat,
  saveExpertTeamSelectionForChat,
} from "./expertTeamSelection";

describe("expertTeamSelection", () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    });
    localStorage.removeItem("qwenpaw-expert-team-selection-by-chat");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists an expert team selection for a specific chat", () => {
    saveExpertTeamSelectionForChat("chat-1", "team-dev");

    expect(loadExpertTeamSelectionForChat("chat-1")).toBe("team-dev");
    expect(loadExpertTeamSelectionForChat("chat-2")).toBeUndefined();
  });

  it("clears only the selected chat", () => {
    saveExpertTeamSelectionForChat("chat-1", "team-dev");
    saveExpertTeamSelectionForChat("chat-2", "team-video");

    clearExpertTeamSelectionForChat("chat-1");

    expect(loadExpertTeamSelectionForChat("chat-1")).toBeUndefined();
    expect(loadExpertTeamSelectionForChat("chat-2")).toBe("team-video");
  });

  it("ignores draft or empty chat ids", () => {
    saveExpertTeamSelectionForChat("", "team-dev");
    saveExpertTeamSelectionForChat(undefined, "team-dev");
    saveExpertTeamSelectionForChat("draft-session", "team-dev");

    expect(loadExpertTeamSelectionForChat("")).toBeUndefined();
    expect(loadExpertTeamSelectionForChat("draft-session")).toBeUndefined();
  });

  it("recovers from corrupted storage", () => {
    localStorage.setItem("qwenpaw-expert-team-selection-by-chat", "{bad json");

    expect(loadExpertTeamSelectionForChat("chat-1")).toBeUndefined();
  });
});
