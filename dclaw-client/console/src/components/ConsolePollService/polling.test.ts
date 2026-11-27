import { describe, expect, it } from "vitest";
import {
  getConsolePollDelay,
  HIDDEN_POLL_INTERVAL_MS,
  VISIBLE_POLL_INTERVAL_MS,
} from "./polling";

describe("ConsolePollService polling", () => {
  it("uses a slower interval for hidden pages", () => {
    expect(getConsolePollDelay("visible")).toBe(VISIBLE_POLL_INTERVAL_MS);
    expect(getConsolePollDelay("hidden")).toBe(HIDDEN_POLL_INTERVAL_MS);
    expect(HIDDEN_POLL_INTERVAL_MS).toBeGreaterThan(VISIBLE_POLL_INTERVAL_MS);
  });
});

