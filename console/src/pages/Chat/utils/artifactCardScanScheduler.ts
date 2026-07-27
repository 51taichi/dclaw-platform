export const ARTIFACT_CARD_SCAN_DELAYS_MS = [100, 500, 1500, 3000] as const;

type ScanTimeoutId = ReturnType<typeof setTimeout>;

type ArtifactCardScanTimers = {
  setTimeout: (handler: () => void, timeout: number) => ScanTimeoutId;
  clearTimeout: (timeoutId: ScanTimeoutId) => void;
};

export function scheduleArtifactCardScans(
  scan: () => void,
  timerApi?: ArtifactCardScanTimers,
): () => void {
  const timers = timerApi ?? {
    setTimeout: (handler: () => void, timeout: number) =>
      setTimeout(handler, timeout),
    clearTimeout: (timeoutId: ScanTimeoutId) => clearTimeout(timeoutId),
  };

  const timeoutIds = ARTIFACT_CARD_SCAN_DELAYS_MS.map((delay) =>
    timers.setTimeout(scan, delay),
  );

  return () => {
    timeoutIds.forEach((timeoutId) => timers.clearTimeout(timeoutId));
  };
}
