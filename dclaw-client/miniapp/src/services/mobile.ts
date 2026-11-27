import Taro from "@tarojs/taro";

import { buildRequestUrl, request } from "./api";
import { getAuthToken } from "./auth";

export type MobileDisplayStatus =
  | "running"
  | "pending_confirmation"
  | "completed"
  | "failed"
  | "idle";

export interface MobileTaskSummary {
  id: string;
  session_id: string;
  name: string;
  agent_id?: string | null;
  expert_team_id?: string | null;
  active_mode?: "craft" | "plan" | "ask" | "" | null;
  runtime_status?: string | null;
  task_status?: string | null;
  display_status: MobileDisplayStatus;
  pending_confirmation_count: number;
  artifact_count: number;
  message_count?: number;
  has_assistant_response?: boolean;
  updated_at?: number | null;
}

export interface MobilePendingConfirmation {
  request_id: string;
  session_id: string;
  root_session_id: string;
  owner_agent_id?: string | null;
  agent_id: string;
  tool_name: string;
  severity: string;
  findings_count: number;
  findings_summary: string;
  tool_params: Record<string, unknown>;
  created_at: number;
  timeout_seconds: number;
}

export type MobileArtifactKind =
  | "image"
  | "document"
  | "archive"
  | "code"
  | "file";

export interface MobileArtifactSummary {
  name: string;
  path: string;
  size?: number | null;
  modified_time?: string | null;
  kind: MobileArtifactKind | string;
}

export interface MobileWorkbenchResponse {
  user_id: string;
  pending_confirmation_count: number;
  running_task_count: number;
  recent_tasks: MobileTaskSummary[];
  recent_results: MobileArtifactSummary[];
}

export interface MobileTaskDetailResponse {
  task: MobileTaskSummary;
  messages: Record<string, unknown>[];
  confirmations: MobilePendingConfirmation[];
  artifacts: MobileArtifactSummary[];
}

export function getWorkbench() {
  return request<MobileWorkbenchResponse>("/mobile/workbench");
}

export function getTasks() {
  return request<MobileTaskSummary[]>("/mobile/tasks");
}

export function getTaskDetail(chatId: string) {
  return request<MobileTaskDetailResponse>(
    `/mobile/tasks/${encodeURIComponent(chatId)}`,
  );
}

export function archiveTask(chatId: string) {
  return request<{ archived: boolean; id: string; archived_at: string }>(
    `/mobile/tasks/${encodeURIComponent(chatId)}/archive`,
    {
      method: "POST",
    },
  );
}

export function deleteTask(chatId: string) {
  return request<{ deleted: boolean; id: string }>(
    `/mobile/tasks/${encodeURIComponent(chatId)}`,
    {
      method: "DELETE",
    },
  );
}

export function getConfirmations() {
  return request<MobilePendingConfirmation[]>("/mobile/confirmations");
}

export function approveConfirmation(requestId: string) {
  return request<{ success: boolean; message: string }>(
    `/mobile/confirmations/${encodeURIComponent(requestId)}/approve`,
    {
      method: "POST",
    },
  );
}

export function denyConfirmation(requestId: string) {
  return request<{ success: boolean; message: string }>(
    `/mobile/confirmations/${encodeURIComponent(requestId)}/deny`,
    {
      method: "POST",
    },
  );
}

export function getResults(chatId: string) {
  return request<MobileArtifactSummary[]>(
    `/mobile/results/${encodeURIComponent(chatId)}`,
  );
}

function encodeWorkspaceFilePath(filePath: string): string {
  return filePath
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export function buildArtifactDownloadUrl(chatId: string, filePath: string) {
  const encodedPath = encodeWorkspaceFilePath(filePath);
  return `${buildRequestUrl(
    "/api/user",
    `/workspace/files/download/${encodedPath}`,
  )}?chatId=${encodeURIComponent(chatId)}`;
}

export async function downloadArtifactFile(
  chatId: string,
  filePath: string,
): Promise<string> {
  const token = getAuthToken();
  const response = await Taro.downloadFile({
    url: buildArtifactDownloadUrl(chatId, filePath),
    header: token ? { Authorization: `Bearer ${token}` } : undefined,
    timeout: 20000,
  });

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(`文件下载失败：${response.statusCode}`);
  }
  if (!response.tempFilePath) {
    throw new Error("文件下载失败：缺少临时文件");
  }
  return response.tempFilePath;
}

export async function saveArtifactImageToAlbum(
  chatId: string,
  filePath: string,
): Promise<void> {
  const tempFilePath = await downloadArtifactFile(chatId, filePath);
  await Taro.saveImageToPhotosAlbum({ filePath: tempFilePath });
}
