import type { MobileWorkbenchResponse } from "../services/mobile";

interface MobileState {
  currentTaskId: string;
  pendingConfirmationCount: number;
}

const state: MobileState = {
  currentTaskId: "",
  pendingConfirmationCount: 0,
};

export function getMobileState(): MobileState {
  return { ...state };
}

export function setCurrentTaskId(taskId: string): void {
  state.currentTaskId = taskId;
}

export function setPendingConfirmationCount(count: number): void {
  state.pendingConfirmationCount = Math.max(0, count);
}

export function applyWorkbenchSummary(summary: MobileWorkbenchResponse): void {
  setPendingConfirmationCount(summary.pending_confirmation_count);
}
