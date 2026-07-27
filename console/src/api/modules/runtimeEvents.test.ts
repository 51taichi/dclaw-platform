import { describe, expect, it } from "vitest";
import {
  buildRuntimeEventsStreamUrl,
  parseRuntimeSseFrame,
  takeRuntimeSseFrames,
} from "./runtimeEvents";

describe("runtimeEvents API helpers", () => {
  it("builds session-scoped stream URLs with optional replay cursor", () => {
    expect(buildRuntimeEventsStreamUrl("session-1", "10-0")).toBe(
      "/api/user/runtime/events/stream?session_id=session-1&since_id=10-0",
    );
  });

  it("extracts complete SSE frames and keeps the partial remainder", () => {
    const { frames, rest } = takeRuntimeSseFrames(
      "event: heartbeat\ndata: {}\n\nevent: runtime_event\ndata:",
    );

    expect(frames).toEqual(["event: heartbeat\ndata: {}"]);
    expect(rest).toBe("event: runtime_event\ndata:");
  });

  it("parses runtime SSE frames", () => {
    const parsed = parseRuntimeSseFrame(
      'event: runtime_event\ndata: {"id":"1","type":"task.progress"}',
    );

    expect(parsed).toEqual({
      event: "runtime_event",
      data: '{"id":"1","type":"task.progress"}',
    });
  });
});
