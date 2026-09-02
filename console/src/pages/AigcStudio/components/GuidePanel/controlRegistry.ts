export const AIGC_PLATFORM_CONTROL_ATTRIBUTE = "data-platform-control-id";

function isActionableControl(control: HTMLElement): boolean {
  if (control.hidden || control.getAttribute("aria-hidden") === "true") {
    return false;
  }
  if (
    control.matches(":disabled") ||
    control.getAttribute("aria-disabled") === "true"
  ) {
    return false;
  }
  const style = window.getComputedStyle(control);
  return style.display !== "none" && style.visibility !== "hidden";
}

export function resolveControl(controlId: string): HTMLElement | null {
  if (!/^[a-z0-9][a-z0-9_.-]+$/.test(controlId)) return null;
  const controls = document.querySelectorAll<HTMLElement>(
    `[${AIGC_PLATFORM_CONTROL_ATTRIBUTE}="${controlId}"]`,
  );
  return Array.from(controls).find(isActionableControl) ?? null;
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
