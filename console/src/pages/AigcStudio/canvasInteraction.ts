import type { AigcCanvas } from "../../api/modules/aigcStudio";

export type CanvasPanState = {
  startClientX: number;
  startClientY: number;
  startViewportX: number;
  startViewportY: number;
};

export type CanvasNodeDragState = {
  nodeId: string;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
};

const VIEWPORT_EXCLUDED_TARGETS = [
  "[data-aigc-node]",
  "button",
  "input",
  "textarea",
  "select",
  "label",
  "[contenteditable='true']",
  "[role='dialog']",
  "[data-aigc-floating-panel]",
].join(",");

export function isCanvasViewportTarget(target: EventTarget | null) {
  const element = target instanceof Element ? target : null;
  if (!element) return true;
  return !element.closest(VIEWPORT_EXCLUDED_TARGETS);
}

export function offsetCanvasViewport({
  viewport,
  deltaX,
  deltaY,
  fallbackScale,
}: {
  viewport: AigcCanvas["viewport"];
  deltaX: number;
  deltaY: number;
  fallbackScale: number;
}): AigcCanvas["viewport"] {
  return {
    ...viewport,
    x: (viewport.x ?? 0) + deltaX,
    y: (viewport.y ?? 0) + deltaY,
    zoom: viewport.zoom ?? fallbackScale,
  };
}

export function panCanvasViewport({
  currentViewport,
  panState,
  clientX,
  clientY,
  fallbackScale,
}: {
  currentViewport?: Partial<AigcCanvas["viewport"]> | null;
  panState: CanvasPanState;
  clientX: number;
  clientY: number;
  fallbackScale: number;
}): AigcCanvas["viewport"] {
  const deltaX = clientX - panState.startClientX;
  const deltaY = clientY - panState.startClientY;
  return {
    x: panState.startViewportX + deltaX,
    y: panState.startViewportY + deltaY,
    zoom: currentViewport?.zoom ?? fallbackScale,
  };
}

export function dragNodePosition({
  dragState,
  clientX,
  clientY,
  viewportScale,
}: {
  dragState: CanvasNodeDragState;
  clientX: number;
  clientY: number;
  viewportScale: number;
}) {
  return {
    x: dragState.startX + (clientX - dragState.startClientX) / viewportScale,
    y: dragState.startY + (clientY - dragState.startClientY) / viewportScale,
  };
}
