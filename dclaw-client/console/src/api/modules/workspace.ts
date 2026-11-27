import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type { MdFileInfo, MdFileContent, DailyMemoryFile } from "../types";

function getSelectedAgentId(): string {
  try {
    // Read from sessionStorage first (per-tab agent), fall back to localStorage
    const agentStorage =
      sessionStorage.getItem("qwenpaw-agent-storage") ||
      localStorage.getItem("qwenpaw-agent-storage");
    if (agentStorage) {
      const parsed = JSON.parse(agentStorage);
      const selectedAgent = parsed?.state?.selectedAgent;
      if (selectedAgent) {
        return selectedAgent;
      }
    }
  } catch (error) {
    console.warn("Failed to get selected agent from storage:", error);
  }
  return "default";
}

function generateFallbackFilename(): string {
  const agentId = getSelectedAgentId();
  const now = new Date();
  const timestamp = now
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\..+/, "")
    .replace("T", "_")
    .slice(0, 15); // YYYYMMDD_HHMMSS
  return `qwenpaw_workspace_${agentId}_${timestamp}.zip`;
}

export interface WorkspaceDownloadResult {
  blob: Blob;
  filename: string;
}

function encodeWorkspacePath(path: string): string {
  return path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
}

function appendQueryParam(path: string, key: string, value?: string): string {
  if (!value) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}${key}=${encodeURIComponent(value)}`;
}

function fallbackFileNameFromPath(path: string, fallback = "download"): string {
  return path.split("/").filter(Boolean).pop() || fallback;
}

function extractDownloadFilename(
  response: Response,
  fallbackFilename: string,
): string {
  const disposition = response.headers.get("Content-Disposition");
  if (!disposition) {
    return fallbackFilename;
  }

  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1]);
    } catch {
      return encodedMatch[1];
    }
  }

  const quotedMatch = disposition.match(/filename="(.+?)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const plainMatch = disposition.match(/filename=([^;]+)/i);
  if (plainMatch?.[1]) {
    return plainMatch[1].trim();
  }

  return fallbackFilename;
}

async function downloadBlob(
  path: string,
  fallbackFilename: string,
  errorLabel = "Download failed",
): Promise<WorkspaceDownloadResult> {
  const response = await fetch(getApiUrl(path), {
    method: "GET",
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(
      `${errorLabel}: ${response.status} ${response.statusText}`,
    );
  }

  return {
    blob: await response.blob(),
    filename: extractDownloadFilename(response, fallbackFilename),
  };
}

export const workspaceApi = {
  listFiles: (chatId?: string) => {
    const url = chatId
      ? `/workspace/files?chatId=${encodeURIComponent(chatId)}`
      : "/workspace/files";
    return request<MdFileInfo[]>(url).then((files) =>
      files.map((file) => ({
        ...file,
        updated_at: new Date(file.modified_time).getTime(),
      })),
    );
  },

  listArtifacts: (chatId?: string) => {
    const url = chatId
      ? `/workspace/artifacts?session_id=${encodeURIComponent(chatId)}`
      : "/workspace/artifacts";
    return request<MdFileInfo[]>(url).then((files) =>
      files.map((file) => ({
        ...file,
        updated_at: new Date(file.modified_time).getTime(),
      })),
    );
  },

  loadFile: (fileName: string, chatId?: string) => {
    const url = chatId
      ? `/workspace/files/${encodeURIComponent(fileName)}?chatId=${encodeURIComponent(chatId)}`
      : `/workspace/files/${encodeURIComponent(fileName)}`;
    return request<MdFileContent>(url);
  },

  loadArtifactFile: (filePath: string, chatId?: string) => {
    const cleanPath = filePath
      .split("/")
      .map(encodeURIComponent)
      .join("/");
    const url = chatId 
      ? `/workspace/files/raw/${cleanPath}?chatId=${encodeURIComponent(chatId)}` 
      : `/workspace/files/raw/${cleanPath}`;
    return request<{ content: string }>(url);
  },

  saveFile: (fileName: string, content: string, chatId?: string) => {
    const url = chatId
      ? `/workspace/files/${encodeURIComponent(fileName)}?chatId=${encodeURIComponent(chatId)}`
      : `/workspace/files/${encodeURIComponent(fileName)}`;
    return request<Record<string, unknown>>(url, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
  },

  // Workspace package download
  downloadWorkspace: async (): Promise<WorkspaceDownloadResult> => {
    return downloadBlob(
      "/user/workspace/download",
      generateFallbackFilename(),
      "Workspace download failed",
    );
  },

  downloadArtifacts: async (
    chatId?: string,
  ): Promise<WorkspaceDownloadResult> => {
    const url = appendQueryParam(
      "/workspace/artifacts/download",
      "session_id",
      chatId,
    );
    return downloadBlob(url, "qwenpaw_artifacts.zip");
  },

  downloadFile: async (
    filePath: string,
    chatId?: string,
  ): Promise<WorkspaceDownloadResult> => {
    const cleanPath = encodeWorkspacePath(filePath);
    const url = appendQueryParam(
      `/workspace/files/download/${cleanPath}`,
      "chatId",
      chatId,
    );
    return downloadBlob(url, fallbackFileNameFromPath(filePath));
  },

  // File upload functionality
  uploadFile: async (
    file: File,
  ): Promise<{ success: boolean; message: string }> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(getApiUrl("/user/workspace/upload"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText} - ${errorText}`,
      );
    }

    return await response.json();
  },

  listDailyMemory: (chatId?: string) => {
    const url = chatId
      ? `/workspace/memory?chatId=${encodeURIComponent(chatId)}`
      : "/workspace/memory";
    return request<MdFileInfo[]>(url).then((files) =>
      files.map((file) => {
        const date = file.filename.replace(".md", "");
        return {
          ...file,
          date,
          updated_at: new Date(file.modified_time).getTime(),
        } as DailyMemoryFile;
      }),
    );
  },

  loadDailyMemory: (date: string, chatId?: string) => {
    const url = chatId
      ? `/workspace/memory/${encodeURIComponent(date)}.md?chatId=${encodeURIComponent(chatId)}`
      : `/workspace/memory/${encodeURIComponent(date)}.md`;
    return request<MdFileContent>(url);
  },

  saveDailyMemory: (date: string, content: string, chatId?: string) => {
    const url = chatId
      ? `/workspace/memory/${encodeURIComponent(date)}.md?chatId=${encodeURIComponent(chatId)}`
      : `/workspace/memory/${encodeURIComponent(date)}.md`;
    return request<Record<string, unknown>>(url, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
  },

  // System prompt files management
  getSystemPromptFiles: () =>
    request<string[]>("/workspace/system-prompt-files"),

  setSystemPromptFiles: (files: string[]) =>
    request<string[]>("/workspace/system-prompt-files", {
      method: "PUT",
      body: JSON.stringify(files),
    }),

  // Workspace Sidebar Core APIs
  listAllFiles: (chatId?: string) => {
    const url = chatId ? `/workspace/all-files?chatId=${encodeURIComponent(chatId)}` : "/workspace/all-files";
    return request<any[]>(url);
  },

  loadRawFile: (filePath: string, chatId?: string) => {
    // Standard segment encoding to preserve '/' path levels and prevent proxy 404s
    const cleanPath = filePath
      .split("/")
      .map(encodeURIComponent)
      .join("/");
    const url = chatId 
      ? `/workspace/files/raw/${cleanPath}?chatId=${encodeURIComponent(chatId)}` 
      : `/workspace/files/raw/${cleanPath}`;
    return request<{ content: string }>(url);
  },

  getWorkspaceChanges: (chatId?: string) => {
    const url = chatId ? `/workspace/changes?chatId=${encodeURIComponent(chatId)}` : "/workspace/changes";
    return request<any[]>(url);
  },

  mergeToMain: (chatId: string) =>
    request<{ merged: boolean; files: string[]; reason?: string }>("/workspace/merge-to-main", {
      method: "POST",
      body: JSON.stringify({ chatId }),
    }),
};
