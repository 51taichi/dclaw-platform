import { afterEach, describe, expect, it, vi } from "vitest";
import { scheduleArtifactCardScans } from "./artifactCardScanScheduler";

describe("scheduleArtifactCardScans", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("runs a bounded set of fallback scans instead of polling forever", () => {
    vi.useFakeTimers();
    const scan = vi.fn();

    scheduleArtifactCardScans(scan);

    vi.advanceTimersByTime(99);
    expect(scan).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(scan).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(400);
    expect(scan).toHaveBeenCalledTimes(2);

    vi.advanceTimersByTime(1000);
    expect(scan).toHaveBeenCalledTimes(3);

    vi.advanceTimersByTime(1500);
    expect(scan).toHaveBeenCalledTimes(4);

    vi.advanceTimersByTime(60_000);
    expect(scan).toHaveBeenCalledTimes(4);
  });

  it("cancels pending fallback scans on cleanup", () => {
    vi.useFakeTimers();
    const scan = vi.fn();

    const cleanup = scheduleArtifactCardScans(scan);
    vi.advanceTimersByTime(100);
    cleanup();
    vi.advanceTimersByTime(60_000);

    expect(scan).toHaveBeenCalledTimes(1);
  });
});
