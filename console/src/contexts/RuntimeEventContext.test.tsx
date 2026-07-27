import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RuntimeEventProvider, useRuntimeEvents } from "./RuntimeEventContext";
import { streamRuntimeEvents } from "../api/modules/runtimeEvents";

vi.mock("../api/modules/runtimeEvents", async () => {
  const actual = await vi.importActual<
    typeof import("../api/modules/runtimeEvents")
  >("../api/modules/runtimeEvents");
  return {
    ...actual,
    streamRuntimeEvents: vi.fn(),
  };
});

function Probe() {
  const { connected, events, setActiveSessionId } = useRuntimeEvents();

  useEffect(() => {
    setActiveSessionId("session-1");
    return () => setActiveSessionId(null);
  }, [setActiveSessionId]);

  return (
    <div>
      <span data-testid="connected">{connected ? "yes" : "no"}</span>
      <span data-testid="events">{events.length}</span>
    </div>
  );
}

describe("RuntimeEventProvider", () => {
  beforeEach(() => {
    vi.mocked(streamRuntimeEvents).mockImplementation(
      async ({ onOpen, onEvent, signal }) => {
        onOpen?.();
        onEvent({
          id: "1-0",
          type: "task.progress",
          scope: "console",
          session_id: "session-1",
          status: "running",
          message: "working",
          payload: {},
          created_at: 1,
        });
        await new Promise<void>((resolve) => {
          signal.addEventListener("abort", () => resolve(), { once: true });
        });
      },
    );
  });

  it("opens one stream for the active session and stores events", async () => {
    render(
      <RuntimeEventProvider>
        <Probe />
      </RuntimeEventProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("connected").textContent).toBe("yes");
      expect(screen.getByTestId("events").textContent).toBe("1");
    });
    expect(streamRuntimeEvents).toHaveBeenCalledTimes(1);
    expect(vi.mocked(streamRuntimeEvents).mock.calls[0][0].sessionId).toBe(
      "session-1",
    );
  });
});
