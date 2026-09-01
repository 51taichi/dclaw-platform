export const AIGC_PLATFORM_CONTROL_ATTRIBUTE = "data-platform-control-id";

export function resolveControl(controlId: string): HTMLElement | null {
  if (!/^[a-z0-9][a-z0-9_.-]+$/.test(controlId)) return null;
  return document.querySelector<HTMLElement>(
    `[${AIGC_PLATFORM_CONTROL_ATTRIBUTE}="${controlId}"]`,
  );
}

export function focusPlatformControl(controlId: string): HTMLElement | null {
  const control = resolveControl(controlId);
  if (!control) return null;
  control.scrollIntoView({ behavior: "smooth", block: "center" });
  control.dataset.platformGuideHighlight = "true";
  window.setTimeout(() => {
    delete control.dataset.platformGuideHighlight;
  }, 1800);
  control.focus({ preventScroll: true });
  return control;
}
