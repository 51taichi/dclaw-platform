import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  FolderOpen,
  Folder,
  FileText,
  FileCode,
  Image,
  File,
  ChevronRight,
  ChevronLeft,
  Download,
  Eye,
  RefreshCw,
  GitBranch,
  Globe,
  ExternalLink,
  ChevronDown,
  CheckCircle2,
  Loader2,
  Circle,
  ListTodo,
} from "lucide-react";
import { workspaceApi } from "../../../api/modules/workspace";
import type { MdFileInfo } from "../../../api/types/workspace";
import { useAgentStore } from "../../../stores/agentStore";
import sessionApi from "../sessionApi";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { importSkillFromContent } from "../utils/skillImport";
import { isInternalTaskFile } from "../utils/artifactFilters";
import { buildWorkspacePreviewUrl } from "./previewUrl";
import {
  getMediaMimeType,
  getMediaPreviewKind,
  isMediaPreviewFile,
} from "./previewMedia";
import styles from "./ArtifactPanel.module.less";
import { chatApi } from "../../../api/modules/chat";
import type { ChatHistory, Message } from "../../../api/types/chat";
import { expertTeamsApi } from "../../../api/modules/expertTeams";
import type { ExpertTeamRun } from "../../../api/types/expertTeams";
import { saveDownloadedBlob } from "../../../utils/download";

// ── File icon & color resolver ───────────────────────────────────

function getFileIcon(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (["md", "txt", "log"].includes(ext)) return <FileText size={16} />;
  if (
    [
      "ts",
      "tsx",
      "js",
      "jsx",
      "py",
      "go",
      "rs",
      "java",
      "c",
      "cpp",
      "h",
      "css",
      "less",
      "scss",
      "html",
      "json",
      "yaml",
      "yml",
    ].includes(ext)
  )
    return <FileCode size={16} />;
  if (["png", "jpg", "jpeg", "gif", "svg", "webp", "ico"].includes(ext))
    return <Image size={16} />;
  return <File size={16} />;
}

function getFileColor(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (["ts", "tsx"].includes(ext)) return "#3178c6";
  if (["js", "jsx"].includes(ext)) return "#f0db4f";
  if (["py"].includes(ext)) return "#3572a5";
  if (["md", "txt"].includes(ext)) return "#6b7280";
  if (["html"].includes(ext)) return "#e34c26";
  if (["css", "less", "scss"].includes(ext)) return "#264de4";
  if (["png", "jpg", "jpeg", "gif", "svg"].includes(ext)) return "#ec4899";
  if (["json"].includes(ext)) return "#f59e0b";
  return "#9ca3af";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function formatTime(dateStr: string): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return `${d.getMonth() + 1}/${d.getDate()} ${d
    .getHours()
    .toString()
    .padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

const isHtmlFile = (filename: string) => {
  return filename?.toLowerCase().endsWith(".html");
};

const isImageFile = (filename: string) => {
  if (!filename) return false;
  const ext = filename.split(".").pop()?.toLowerCase();
  return ["png", "jpg", "jpeg", "gif", "svg", "webp", "ico"].includes(
    ext || "",
  );
};

const TEXT_PREVIEW_EXTENSIONS = new Set([
  "md",
  "txt",
  "log",
  "csv",
  "json",
  "jsonl",
  "yaml",
  "yml",
  "toml",
  "ini",
  "env",
  "xml",
  "html",
  "css",
  "less",
  "scss",
  "js",
  "jsx",
  "ts",
  "tsx",
  "py",
  "go",
  "rs",
  "java",
  "c",
  "cpp",
  "h",
  "hpp",
  "sh",
  "bash",
  "zsh",
  "sql",
]);

const TEXT_PREVIEW_FILENAMES = new Set([
  ".env",
  ".gitignore",
  "Dockerfile",
  "Makefile",
  "README",
  "LICENSE",
]);

function getFileExtension(filename: string): string {
  const basename = filename.split("/").filter(Boolean).pop() || filename;
  if (!basename.includes(".")) return "";
  return basename.split(".").pop()?.toLowerCase() || "";
}

export function isTextPreviewFile(filename: string) {
  if (!filename) return false;
  if (filename === "task.md" || isHtmlFile(filename)) return true;
  if (isImageFile(filename) || isMediaPreviewFile(filename)) return false;
  const basename = filename.split("/").filter(Boolean).pop() || filename;
  if (TEXT_PREVIEW_FILENAMES.has(basename)) return true;
  return TEXT_PREVIEW_EXTENSIONS.has(getFileExtension(filename));
}

export function isDownloadOnlyPreviewFile(filename: string) {
  return (
    !!filename &&
    !isTextPreviewFile(filename) &&
    !isImageFile(filename) &&
    !isMediaPreviewFile(filename)
  );
}

// ── Recursive File Tree Node Interface ────────────────────────────

interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  size?: number;
  modifiedTime?: string;
  children?: FileNode[];
}

interface GitChange {
  filepath: string;
  status: string; // e.g. "M", "A", "??", "D"
  diff: string;
}

interface ArtifactPanelProps {
  visible?: boolean;
  onToggle?: () => void;
  isClawMode?: boolean;
  chatId?: string;
}

interface TaskItem {
  text: string;
  status: "completed" | "in_progress" | "pending";
  level: number;
}

interface DerivedTaskBoard {
  tasks: TaskItem[];
  source: "expert-team" | "task-file" | "artifacts" | "text-output" | "empty";
}

// ── Markdown Task Parser ─────────────────────────────────────────

function parseTaskMarkdown(content: string): TaskItem[] {
  if (!content) return [];
  const lines = content.split(/\r?\n/);
  const tasks: TaskItem[] = [];

  for (const line of lines) {
    const match = line.match(/^(\s*)-\s*\[([ xX/])\]\s*(.*)$/);
    if (match) {
      const indent = match[1].length;
      const statusChar = match[2].toLowerCase();
      const text = match[3].trim();

      let status: TaskItem["status"] = "pending";
      if (statusChar === "x") {
        status = "completed";
      } else if (statusChar === "/") {
        status = "in_progress";
      }

      tasks.push({
        text,
        status,
        level: Math.floor(indent / 2),
      });
    }
  }
  return tasks;
}

const getMockTasks = (): TaskItem[] => [];

export function buildArtifactDerivedTasks(
  artifactList: (MdFileInfo & { isVirtual?: boolean })[],
): TaskItem[] {
  const visibleFiles = artifactList.filter(
    (item) => item.path && item.path !== "task.md" && !item.isVirtual,
  );

  if (visibleFiles.length === 0) return [];

  const tasks: TaskItem[] = [
    {
      text: `整理本次任务产物（${visibleFiles.length} 个文件）`,
      status: "completed",
      level: 0,
    },
  ];

  const htmlFiles = visibleFiles.filter((item) => isHtmlFile(item.path));
  const mediaFiles = visibleFiles.filter((item) =>
    isMediaPreviewFile(item.path),
  );

  visibleFiles.slice(0, 8).forEach((item) => {
    tasks.push({
      text: `生成 ${item.path}`,
      status: "completed",
      level: 1,
    });
  });

  if (visibleFiles.length > 8) {
    tasks.push({
      text: `还有 ${visibleFiles.length - 8} 个文件可在“文件”页签查看`,
      status: "completed",
      level: 1,
    });
  }

  if (htmlFiles.length > 0) {
    tasks.push({
      text: "网页产物已接入右侧内置浏览器预览",
      status: "completed",
      level: 0,
    });
  }

  if (mediaFiles.length > 0) {
    tasks.push({
      text: "音视频产物已接入右侧播放器预览",
      status: "completed",
      level: 0,
    });
  }

  return tasks;
}

function extractPlainText(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";

  return content
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const record = item as Record<string, unknown>;
      if (record.type === "text" && typeof record.text === "string") {
        return record.text;
      }
      return "";
    })
    .join("\n")
    .trim();
}

export function buildTextOutputDerivedTasks(
  chatHistory: ChatHistory | null,
): TaskItem[] {
  if (!chatHistory) return [];

  if (chatHistory.status === "running") {
    return [
      {
        text: "正在生成文字结果",
        status: "in_progress",
        level: 0,
      },
    ];
  }

  const hasAssistantText = (chatHistory.messages || []).some(
    (message: Message) =>
      message.role === "assistant" && extractPlainText(message.content),
  );

  if (!hasAssistantText) return [];

  return [
    {
      text: "完成文字结果输出",
      status: "completed",
      level: 0,
    },
  ];
}

export function buildExpertTeamRunTasks(run: ExpertTeamRun | null): TaskItem[] {
  if (!run || !Array.isArray(run.members) || run.members.length === 0) {
    return [];
  }

  return run.members.map((member) => {
    const label = member.role
      ? `${member.display_name}：${member.role}`
      : member.display_name;
    let status: TaskItem["status"] = "pending";
    if (member.state === "completed") {
      status = "completed";
    } else if (member.state === "running") {
      status = "in_progress";
    }

    return {
      text:
        member.state === "failed"
          ? `${label} 失败：${member.error || "等待重新处理"}`
          : member.state === "cancelled"
          ? `${label} 已取消`
          : label,
      status,
      level: Math.max(0, member.stage_index || 0),
    };
  });
}

export default function ArtifactPanel({
  visible = false,
  onToggle,
  isClawMode,
  chatId,
}: ArtifactPanelProps) {
  const { t } = useTranslation();

  const store = useAgentStore();
  const currentExpertTeamRun = store.currentExpertTeamRun;
  const setCurrentExpertTeamRun = store.setCurrentExpertTeamRun;
  const { message } = useAppMessage();
  const currentIsClawMode =
    isClawMode !== undefined
      ? isClawMode
      : window.location.pathname.startsWith("/claw");
  const selectedAgent = currentIsClawMode
    ? store.clawSelectedAgent
    : store.selectedAgent;

  const realChatId =
    (chatId && sessionApi.getRealIdForSession(chatId)) || chatId;
  const [previewContextChatId, setPreviewContextChatId] = useState<
    string | null
  >(realChatId || null);

  useEffect(() => {
    let cancelled = false;
    const activeChatId = realChatId || null;

    if (!activeChatId) {
      setPreviewContextChatId(null);
      return;
    }

    setPreviewContextChatId(activeChatId);
    sessionApi.getSessionIdForChatId(activeChatId).then((sessionId) => {
      if (!cancelled) {
        setPreviewContextChatId(sessionId || activeChatId);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [realChatId]);

  // Active Tab: 'artifacts' | 'files' | 'changes' | 'browser'
  const [activeTab, setActiveTab] = useState<
    "artifacts" | "files" | "changes" | "browser"
  >("artifacts");

  // 1. Artifacts Tab States
  const [artifacts, setArtifacts] = useState<
    (MdFileInfo & { updated_at?: number; isVirtual?: boolean })[]
  >([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [artifactContent, setArtifactContent] = useState<string>("");
  const [artifactContentLoading, setArtifactContentLoading] = useState(false);
  const [textOutputTasks, setTextOutputTasks] = useState<TaskItem[]>([]);
  const [expertTeamRun, setExpertTeamRun] = useState<ExpertTeamRun | null>(
    currentExpertTeamRun,
  );

  // 2. All Files Tab States
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>(
    {},
  );
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [rawFileContent, setRawFileContent] = useState<string>("");
  const [rawFileContentLoading, setRawFileContentLoading] = useState(false);

  // 3. Changes Tab States
  const [changes, setChanges] = useState<GitChange[]>([]);
  const [changesLoading, setChangesLoading] = useState(false);
  const [activeChangePath, setActiveChangePath] = useState<string | null>(null);
  const [activeDiffText, setActiveDiffText] = useState<string>("");

  // 4. Builtin Web Browser States
  const [previewPath, setPreviewPath] = useState<string>("index.html");
  const [browserInput, setBrowserInput] = useState<string>("index.html");
  const [iframeKey, setIframeKey] = useState<number>(0);

  // 5. Advanced Double Mode Toggle for HTML
  const [previewMode, setPreviewMode] = useState<"run" | "code">("run");

  // ── Resizing Logic ────────────────────────────────────────────────
  const hasPreview = !!(
    selectedArtifact ||
    selectedFilePath ||
    activeChangePath
  );
  const [panelWidth, setPanelWidth] = useState<number>(400);
  const [isResizing, setIsResizing] = useState(false);

  useEffect(() => {
    if (!isResizing) {
      setPanelWidth(hasPreview ? 780 : 400);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPreview]);

  const startResizing = useCallback((e: React.MouseEvent) => {
    setIsResizing(true);
    e.preventDefault();
  }, []);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      // The panel is on the right side of the screen
      const newWidth = window.innerWidth - e.clientX;
      const minWidth = 320;
      const maxWidth = window.innerWidth * 0.8;

      if (newWidth > minWidth && newWidth < maxWidth) {
        setPanelWidth(newWidth);
      } else if (newWidth <= minWidth) {
        setPanelWidth(minWidth);
      } else if (newWidth >= maxWidth) {
        setPanelWidth(maxWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    // Disable text selection and change cursor globally during drag
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizing]);

  // Helper to construct correct preview URLs with session parameters
  const getPreviewUrl = useCallback(
    (path: string, version?: number) => {
      return buildWorkspacePreviewUrl({
        path,
        agentId: selectedAgent,
        chatId: previewContextChatId || realChatId,
        version,
      });
    },
    [selectedAgent, previewContextChatId, realChatId],
  );

  const renderMediaPreview = useCallback(
    (path: string) => {
      const kind = getMediaPreviewKind(path);
      const mimeType = getMediaMimeType(path);
      const url = getPreviewUrl(path);

      if (kind === "audio") {
        return (
          <div className={styles.mediaPreview}>
            <div className={styles.audioPreviewCard}>
              <File size={36} strokeWidth={1.5} />
              <span className={styles.mediaFileName}>
                {path.split("/").pop()}
              </span>
              <audio controls preload="metadata" className={styles.audioPlayer}>
                <source src={url} type={mimeType} />
                当前浏览器无法播放此音频。
              </audio>
            </div>
          </div>
        );
      }

      if (kind === "video") {
        return (
          <div className={styles.mediaPreview}>
            <video controls preload="metadata" className={styles.videoPlayer}>
              <source src={url} type={mimeType} />
              当前浏览器无法播放此视频。
            </video>
          </div>
        );
      }

      return null;
    },
    [getPreviewUrl],
  );

  // Auto Reset Preview Mode when files are selected
  useEffect(() => {
    const currentFile = selectedArtifact || selectedFilePath;
    if (currentFile && isHtmlFile(currentFile)) {
      setPreviewMode("run");
    } else {
      setPreviewMode("code");
    }
  }, [selectedArtifact, selectedFilePath]);

  // ── Unified Data Loader ──────────────────────────────────────────

  const loadTextOutputTasks = useCallback(async () => {
    if (!realChatId) {
      setTextOutputTasks([]);
      return;
    }

    try {
      const chatHistory = await chatApi.getChat(realChatId, selectedAgent);
      setTextOutputTasks(buildTextOutputDerivedTasks(chatHistory));
    } catch {
      setTextOutputTasks([]);
    }
  }, [realChatId, selectedAgent]);

  const loadExpertTeamRun = useCallback(async () => {
    if (!realChatId) {
      setExpertTeamRun(null);
      setCurrentExpertTeamRun(null);
      return null;
    }

    try {
      const run = await expertTeamsApi.getRunByChat(realChatId);
      setExpertTeamRun(run);
      setCurrentExpertTeamRun(run);
      return run;
    } catch {
      setExpertTeamRun(null);
      return null;
    }
  }, [realChatId, setCurrentExpertTeamRun]);

  const loadData = useCallback(
    async (tabName = activeTab) => {
      if (tabName === "artifacts") {
        setArtifactsLoading(true);
        try {
          const result = await workspaceApi.listArtifacts(realChatId);
          const rawList = Array.isArray(result) ? result : [];
          const list = rawList.filter((item) => {
            const path = item.path || "";
            return !(
              isInternalTaskFile(path) ||
              path.startsWith("browser/user_data/") ||
              path.startsWith("node_modules/") ||
              path.startsWith(".gemini/") ||
              path.startsWith(".git/") ||
              path.startsWith(".DS_Store")
            );
          });

          // Force inject/prepend the "任务列表" (Virtual task.md)
          const virtualTask = {
            filename: "任务列表",
            path: "task.md",
            size: 0,
            created_time: new Date().toISOString(),
            modified_time: new Date().toISOString(),
            isVirtual: true,
          };

          const hasTask = list.some((item) => item.path === "task.md");
          if (!hasTask) {
            setArtifacts([virtualTask, ...list]);
          } else {
            const filtered = list.filter((item) => item.path !== "task.md");
            setArtifacts([virtualTask, ...filtered]);
          }

          const hasVisibleArtifacts = list.some(
            (item) => item.path && item.path !== "task.md",
          );
          const run = await loadExpertTeamRun();
          if (!run && !hasTask && !hasVisibleArtifacts) {
            await loadTextOutputTasks();
          } else {
            setTextOutputTasks([]);
          }
        } catch {
          // ignore
        } finally {
          setArtifactsLoading(false);
        }
      } else if (tabName === "files") {
        setFilesLoading(true);
        try {
          const result = await workspaceApi.listAllFiles(realChatId);
          const rawList = Array.isArray(result) ? result : [];
          const list = rawList.filter((item) => {
            const path = item.path || "";
            return !(
              isInternalTaskFile(path) ||
              path.startsWith("browser/user_data/") ||
              path.startsWith("node_modules/") ||
              path.startsWith(".gemini/") ||
              path.startsWith(".git/") ||
              path.startsWith(".DS_Store")
            );
          });
          setFileTree(list);
        } catch {
          // ignore
        } finally {
          setFilesLoading(false);
        }
      } else if (tabName === "changes") {
        setChangesLoading(true);
        try {
          const result = await workspaceApi.getWorkspaceChanges(realChatId);
          const rawList = Array.isArray(result) ? result : [];
          const list = rawList.filter((item) => {
            const path = item.path || "";
            return !(
              isInternalTaskFile(path) ||
              path.startsWith("browser/user_data/") ||
              path.startsWith("node_modules/") ||
              path.startsWith(".gemini/") ||
              path.startsWith(".git/") ||
              path.startsWith(".DS_Store")
            );
          });
          setChanges(list);
        } catch {
          // ignore
        } finally {
          setChangesLoading(false);
        }
      }
    },
    [activeTab, realChatId, loadTextOutputTasks, loadExpertTeamRun],
  );

  useEffect(() => {
    if (!visible || !realChatId) return;

    let cancelled = false;
    let inFlight = false;
    const shouldPoll = () => {
      const state = expertTeamRun?.state;
      return !state || state === "pending" || state === "running";
    };

    const refresh = async () => {
      if (!cancelled && !inFlight && document.visibilityState !== "hidden") {
        inFlight = true;
        try {
          await loadExpertTeamRun();
        } finally {
          inFlight = false;
        }
      }
    };

    refresh();
    if (!shouldPoll()) {
      return () => {
        cancelled = true;
      };
    }

    const timer = window.setInterval(() => {
      if (shouldPoll()) {
        refresh();
      }
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [visible, realChatId, loadExpertTeamRun, expertTeamRun?.state]);

  // ── Auto Redirect previewPath to session's first HTML artifact ──
  useEffect(() => {
    if (previewPath === "index.html") {
      // 1. Check session-isolated artifacts first (highest priority)
      const htmlArtifacts = artifacts.filter(
        (item) =>
          item.path &&
          item.path.toLowerCase().endsWith(".html") &&
          !item.isVirtual,
      );
      if (htmlArtifacts.length > 0) {
        // Prefer index.html from session artifacts if present
        const sessionIndex = htmlArtifacts.find(
          (item) =>
            item.path === "index.html" || item.path.endsWith("/index.html"),
        );
        if (sessionIndex) {
          // index.html is in session artifacts — keep default, no redirect needed
          return;
        }
        // Session has HTML artifacts but none is index.html → redirect to first
        const gameHtml = htmlArtifacts.find((item) =>
          item.path.toLowerCase().includes("game"),
        );
        const targetPath = gameHtml ? gameHtml.path : htmlArtifacts[0].path;
        setPreviewPath(targetPath);
        setBrowserInput(targetPath);
        return;
      }

      // 2. Fallback: check fileTree recursively (for non-session-aware mode)
      if (fileTree.length > 0) {
        const allHtmlFiles: string[] = [];
        const traverse = (nodes: FileNode[]) => {
          for (const node of nodes) {
            if (!node.isDir && node.name.toLowerCase().endsWith(".html")) {
              allHtmlFiles.push(node.path);
            } else if (node.isDir && node.children) {
              traverse(node.children);
            }
          }
        };
        traverse(fileTree);

        if (allHtmlFiles.length > 0) {
          const hasIndex = allHtmlFiles.some(
            (p) => p === "index.html" || p.endsWith("/index.html"),
          );
          if (!hasIndex) {
            const gameHtml = allHtmlFiles.find((p) =>
              p.toLowerCase().includes("game"),
            );
            const targetPath = gameHtml || allHtmlFiles[0];
            setPreviewPath(targetPath);
            setBrowserInput(targetPath);
          }
        }
      }
    }
  }, [artifacts, fileTree, previewPath]);

  // Reset browser preview path when session changes
  useEffect(() => {
    setPreviewPath("index.html");
    setBrowserInput("index.html");
  }, [chatId]);

  // Load data when panel opens, tab changes, or chatId changes
  useEffect(() => {
    if (visible) {
      loadData(activeTab);
    }
  }, [visible, activeTab, loadData, chatId]);

  // ── Artifact Action ──────────────────────────────────────────────

  const handlePreviewArtifact = useCallback(
    async (filePath: string, eventChatId?: string) => {
      // Clear other tab selected states to prevent preview conflicts
      setSelectedFilePath(null);
      setActiveChangePath(null);

      setSelectedArtifact(filePath);
      setArtifactContentLoading(true);
      try {
        const activeChatId =
          (eventChatId && sessionApi.getRealIdForSession(eventChatId)) ||
          eventChatId ||
          realChatId;
        if (!isTextPreviewFile(filePath)) {
          setArtifactContent("");
          return;
        }
        const result = await workspaceApi.loadArtifactFile(
          filePath,
          activeChatId,
        );
        setArtifactContent(result.content || "");
      } catch {
        if (filePath === "task.md") {
          // Fallback for visual task list if reading task.md fails
          setArtifactContent(`
# 任务进度看板

当前暂无活跃的待办任务。大模型制定计划后将在此处展示。
        `);
        } else {
          setArtifactContent("Failed to load file.");
        }
      } finally {
        setArtifactContentLoading(false);
      }
    },
    [realChatId],
  );

  const handleDownloadArtifacts = useCallback(async () => {
    try {
      const { blob, filename } = await workspaceApi.downloadArtifacts(
        realChatId,
      );
      if (await saveDownloadedBlob(blob, filename)) {
        message.success("产物包已保存");
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      message.error(`产物下载失败: ${errorMessage}`);
    }
  }, [message, realChatId]);

  const handleDownloadFile = useCallback(
    async (filePath: string) => {
      try {
        const { blob, filename } = await workspaceApi.downloadFile(
          filePath,
          realChatId,
        );
        if (await saveDownloadedBlob(blob, filename)) {
          message.success("文件已保存");
        }
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : String(error);
        message.error(`文件下载失败: ${errorMessage}`);
      }
    },
    [message, realChatId],
  );

  // ── All Files Action ─────────────────────────────────────────────

  const toggleDirectory = useCallback((path: string) => {
    setExpandedPaths((prev) => ({
      ...prev,
      [path]: !prev[path],
    }));
  }, []);

  const handleLoadRawFile = useCallback(
    async (path: string) => {
      // Clear other tab selected states to prevent preview conflicts
      setSelectedArtifact(null);
      setActiveChangePath(null);

      setSelectedFilePath(path);
      setRawFileContentLoading(true);
      try {
        if (!isTextPreviewFile(path)) {
          setRawFileContent("");
          return;
        }
        const result = await workspaceApi.loadRawFile(path, realChatId);
        setRawFileContent(result.content || "");
      } catch {
        setRawFileContent("Failed to load file contents.");
      } finally {
        setRawFileContentLoading(false);
      }
    },
    [realChatId],
  );

  // ── Git Changes Action ────────────────────────────────────────────

  const handleSelectChange = useCallback((item: GitChange) => {
    // Clear other tab selected states to prevent preview conflicts
    setSelectedArtifact(null);
    setSelectedFilePath(null);

    setActiveChangePath(item.filepath);
    setActiveDiffText(item.diff || "");
  }, []);

  // ── Builtin Browser Action ────────────────────────────────────────

  const handleBrowserNavigate = (e: React.FormEvent) => {
    e.preventDefault();
    if (browserInput.trim()) {
      setPreviewPath(browserInput.trim());
      setIframeKey((k) => k + 1);
    }
  };

  const handleBrowserRefresh = () => {
    setIframeKey((k) => k + 1);
  };

  const handleBrowserOpenExternal = () => {
    const iframeUrl = getPreviewUrl(previewPath);
    window.open(iframeUrl, "_blank");
  };

  // ── Listen to cross-component "preview-artifact" custom events ───
  useEffect(() => {
    const handlePreviewEvent = (e: Event) => {
      const customEvent = e as CustomEvent<{
        path?: string;
        activeTab?: string;
        chatId?: string;
      }>;
      if (!customEvent.detail) return;

      const {
        path,
        activeTab: targetTab,
        chatId: eventChatId,
      } = customEvent.detail;

      // 1. If panel is closed, expand it
      if (!visible && onToggle) {
        onToggle();
      }

      // 2. Map tab name: products -> artifacts, browser -> browser, changes -> changes, files -> files
      let tabName: "artifacts" | "files" | "changes" | "browser" = "artifacts";
      if (targetTab === "products") {
        tabName = "artifacts";
      } else if (targetTab === "browser") {
        tabName = "browser";
      } else if (targetTab === "changes") {
        tabName = "changes";
      } else if (targetTab === "files") {
        tabName = "files";
      }

      setActiveTab(tabName);

      // 3. Handle target tab selection & content loading
      if (tabName === "artifacts" && path) {
        handlePreviewArtifact(path, eventChatId);
      } else if (tabName === "browser") {
        if (path) {
          setPreviewPath(path);
          setBrowserInput(path);
        }
        setIframeKey((k) => k + 1);
      } else if (tabName === "changes" && path) {
        workspaceApi
          .getWorkspaceChanges(realChatId)
          .then((result) => {
            const list = Array.isArray(result) ? result : [];
            setChanges(list);
            const found = list.find((item) => item.filepath === path);
            if (found) {
              handleSelectChange(found);
            } else {
              setActiveChangePath(path);
              setActiveDiffText("No local changes detected for this file.");
            }
          })
          .catch(() => {
            setActiveChangePath(path);
            setActiveDiffText("No local changes detected for this file.");
          });
      } else if (tabName === "files" && path) {
        handleLoadRawFile(path);
      }
    };

    window.addEventListener("preview-artifact", handlePreviewEvent);
    return () => {
      window.removeEventListener("preview-artifact", handlePreviewEvent);
    };
  }, [
    visible,
    onToggle,
    realChatId,
    handlePreviewArtifact,
    handleSelectChange,
    handleLoadRawFile,
  ]);

  // ── Dock Tooltip click actions ───────────────────────────────────

  const handleDockClick = (
    tab: "artifacts" | "files" | "changes" | "browser",
  ) => {
    setActiveTab(tab);
    if (!visible && onToggle) {
      onToggle();
    }
  };

  // ── Sub-render for workspace recursive directory tree ───────────

  const renderFileTreeNodes = (nodes: FileNode[], level = 0) => {
    return nodes.map((node) => {
      const isExpanded = !!expandedPaths[node.path];
      const isSelected = selectedFilePath === node.path;

      if (node.isDir) {
        return (
          <div key={node.path} className={styles.treeDirWrapper}>
            <div
              className={styles.treeDirHeader}
              style={{ paddingLeft: `${level * 14 + 6}px` }}
              onClick={() => toggleDirectory(node.path)}
            >
              <span className={styles.treeChevron}>
                <ChevronDown
                  size={14}
                  className={`${styles.chevronIcon} ${
                    isExpanded ? "" : styles.chevronRotate
                  }`}
                />
              </span>
              <Folder size={14} className={styles.folderIcon} />
              <span className={styles.treeNodeName}>{node.name}</span>
            </div>
            {isExpanded && node.children && (
              <div className={styles.treeChildren}>
                {renderFileTreeNodes(node.children, level + 1)}
              </div>
            )}
          </div>
        );
      } else {
        return (
          <div
            key={node.path}
            className={`${styles.treeFileItem} ${
              isSelected ? styles.treeFileActive : ""
            }`}
            style={{ paddingLeft: `${level * 14 + 20}px` }}
            onClick={() => handleLoadRawFile(node.path)}
          >
            <span
              className={styles.fileIcon}
              style={{ color: getFileColor(node.name) }}
            >
              {getFileIcon(node.name)}
            </span>
            <span className={styles.treeNodeName}>{node.name}</span>
            {node.size !== undefined && (
              <span className={styles.treeFileSize}>
                {formatFileSize(node.size)}
              </span>
            )}
          </div>
        );
      }
    });
  };

  // ── Diff Viewer Highlighter ──────────────────────────────────────

  const renderDiffContent = (diffText: string) => {
    if (!diffText) return <div className={styles.diffEmpty}>No diff text</div>;
    const lines = diffText.split("\n");
    return (
      <div className={styles.diffLines}>
        {lines.map((line, idx) => {
          let lineClass = styles.diffLine;
          if (line.startsWith("+") && !line.startsWith("+++")) {
            lineClass = `${styles.diffLine} ${styles.diffAdd}`;
          } else if (line.startsWith("-") && !line.startsWith("---")) {
            lineClass = `${styles.diffLine} ${styles.diffDel}`;
          } else if (line.startsWith("@@")) {
            lineClass = `${styles.diffLine} ${styles.diffInfo}`;
          }
          return (
            <div key={idx} className={lineClass}>
              <span className={styles.diffLineNumber}>{idx + 1}</span>
              <span className={styles.diffLineText}>{line}</span>
            </div>
          );
        })}
      </div>
    );
  };

  // ── Render Dock Toolbar (When sidebar is collapsed) ──────────────

  if (!visible) {
    return (
      <div className={styles.dockBar}>
        <button
          className={styles.dockBtn}
          onClick={onToggle}
          title={t("artifact.showPanel", "展开侧边栏")}
        >
          <ChevronLeft size={16} />
        </button>
        <div className={styles.dockDivider} />
        <button
          className={`${styles.dockItem} ${
            activeTab === "artifacts" ? styles.dockItemActive : ""
          }`}
          onClick={() => handleDockClick("artifacts")}
        >
          <FileText size={18} />
          <span className={styles.dockTooltip}>
            {t("artifact.tab.artifacts", "产物")}
          </span>
        </button>
        <button
          className={`${styles.dockItem} ${
            activeTab === "files" ? styles.dockItemActive : ""
          }`}
          onClick={() => handleDockClick("files")}
        >
          <FolderOpen size={18} />
          <span className={styles.dockTooltip}>
            {t("artifact.tab.files", "全部文件")}
          </span>
        </button>
        <button
          className={`${styles.dockItem} ${
            activeTab === "changes" ? styles.dockItemActive : ""
          }`}
          onClick={() => handleDockClick("changes")}
        >
          <GitBranch size={18} />
          <span className={styles.dockTooltip}>
            {t("artifact.tab.changes", "代码变更")}
          </span>
        </button>
        <button
          className={`${styles.dockItem} ${
            activeTab === "browser" ? styles.dockItemActive : ""
          }`}
          onClick={() => handleDockClick("browser")}
        >
          <Globe size={18} />
          <span className={styles.dockTooltip}>
            {t("artifact.tab.browser", "内置浏览器")}
          </span>
        </button>
      </div>
    );
  }

  // ── Sub-renders for Visual Task Board and Preview Column ──────────

  const renderTaskBoard = () => {
    const parsedTasks = parseTaskMarkdown(artifactContent);
    const expertTeamTasks = buildExpertTeamRunTasks(expertTeamRun);
    const derivedTasks = buildArtifactDerivedTasks(artifacts);
    const board: DerivedTaskBoard =
      expertTeamTasks.length > 0
        ? { tasks: expertTeamTasks, source: "expert-team" }
        : parsedTasks.length > 0
        ? { tasks: parsedTasks, source: "task-file" }
        : derivedTasks.length > 0
        ? { tasks: derivedTasks, source: "artifacts" }
        : textOutputTasks.length > 0
        ? { tasks: textOutputTasks, source: "text-output" }
        : { tasks: getMockTasks(), source: "empty" };
    const finalTasks = board.tasks;
    const completedCount = finalTasks.filter(
      (t) => t.status === "completed",
    ).length;
    const totalCount = finalTasks.length;
    const percent =
      totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

    return (
      <div className={styles.taskBoard}>
        <div className={styles.taskBoardHeader}>
          <div className={styles.taskBoardTitle}>
            <ListTodo size={20} style={{ color: "#2563eb" }} />
            <span>待办任务进度</span>
          </div>
          {board.source === "artifacts" && (
            <div className={styles.taskBoardHint}>
              当前会话没有生成独立的 task.md，已根据任务产物自动汇总完成事项。
            </div>
          )}
          {board.source === "expert-team" && (
            <div className={styles.taskBoardHint}>
              正在展示专家团成员分工进度。成员产物会继续汇总到当前会话。
            </div>
          )}
          {board.source === "text-output" && (
            <div className={styles.taskBoardHint}>
              当前会话没有生成文件产物，已根据文字回复自动汇总完成状态。
            </div>
          )}
        </div>

        <div className={styles.taskStatsCard}>
          <div className={styles.taskStatsInfo}>
            <span className={styles.taskStatsCount}>
              已完成 <strong>{completedCount}</strong> / {totalCount} 个任务
            </span>
            <span className={styles.taskStatsPercent}>{percent}%</span>
          </div>
          <div className={styles.progressBarWrapper}>
            <div
              className={styles.progressBarFill}
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>

        <div className={styles.taskList}>
          {finalTasks.length === 0 ? (
            <div
              className={styles.taskCard}
              style={{
                color: "#9ca3af",
                justifyContent: "center",
                padding: "30px 20px",
              }}
            >
              <span>
                暂无任务记录。生成 task.md 或任务产物后，会在这里展示进度。
              </span>
            </div>
          ) : (
            finalTasks.map((task, index) => {
              let cardClass = styles.taskCard;
              let icon = (
                <Circle size={16} className={styles.taskIconPending} />
              );

              if (task.status === "completed") {
                cardClass = `${styles.taskCard} ${styles.taskCardCompleted}`;
                icon = (
                  <CheckCircle2
                    size={16}
                    className={styles.taskIconCompleted}
                  />
                );
              } else if (task.status === "in_progress") {
                cardClass = `${styles.taskCard} ${styles.taskCardInProgress}`;
                icon = (
                  <Loader2
                    size={16}
                    className={`${styles.taskIconInProgress} ${styles.spinning}`}
                  />
                );
              } else {
                cardClass = `${styles.taskCard} ${styles.taskCardPending}`;
              }

              return (
                <div
                  key={index}
                  className={cardClass}
                  style={{ marginLeft: `${task.level * 16}px` }}
                >
                  <div className={styles.taskIconWrapper}>{icon}</div>
                  <span className={styles.taskText}>{task.text}</span>
                </div>
              );
            })
          )}
        </div>
      </div>
    );
  };
  const handleImportSkill = async (content: string) => {
    try {
      message.loading({ content: "正在导入技能...", key: "importSkill" });
      const result = await importSkillFromContent(content, {
        targetAgentId: selectedAgent,
      });
      message.success({
        content: `✨ 技能「${result.name}」已成功导入到“我的技能”并启用！`,
        key: "importSkill",
        duration: 3,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      message.error({
        content: `导入失败: ${errorMessage}`,
        key: "importSkill",
      });
    }
  };

  const renderPreviewEngine = () => {
    const renderDownloadOnlyPreview = (path: string) => {
      const filename = path.split("/").filter(Boolean).pop() || path;
      return (
        <div className={styles.downloadOnlyPreview}>
          <div
            className={styles.downloadOnlyIcon}
            style={{ color: getFileColor(filename) }}
          >
            {getFileIcon(filename)}
          </div>
          <div className={styles.downloadOnlyTitle}>{filename}</div>
          <div className={styles.downloadOnlyMeta}>
            该文件类型不支持内嵌预览
          </div>
          <button
            type="button"
            className={styles.downloadPrimaryButton}
            onClick={() => handleDownloadFile(path)}
          >
            <Download size={15} />
            <span>下载文件</span>
          </button>
        </div>
      );
    };

    if (selectedArtifact) {
      const isTaskList = selectedArtifact === "task.md";
      const isHtml = isHtmlFile(selectedArtifact);
      const isImage = isImageFile(selectedArtifact);
      const isMedia = isMediaPreviewFile(selectedArtifact);
      const isDownloadOnly = isDownloadOnlyPreviewFile(selectedArtifact);
      const displayName = isTaskList ? "📋 任务列表" : selectedArtifact;
      const hasSkillMeta =
        artifactContent &&
        /---[\s\S]*?name:\s*([^\r\n]+)[\s\S]*?---/i.test(artifactContent);

      return (
        <>
          <div className={styles.previewHeader}>
            <span className={styles.previewFileName}>{displayName}</span>

            {isHtml && (
              <div className={styles.toggleGroup}>
                <button
                  type="button"
                  className={`${styles.toggleBtn} ${
                    previewMode === "run" ? styles.toggleBtnActive : ""
                  }`}
                  onClick={() => setPreviewMode("run")}
                >
                  <span className={styles.toggleIcon}>🎮</span> 运行预览
                </button>
                <button
                  type="button"
                  className={`${styles.toggleBtn} ${
                    previewMode === "code" ? styles.toggleBtnActive : ""
                  }`}
                  onClick={() => setPreviewMode("code")}
                >
                  <span className={styles.toggleIcon}>📝</span> 源码内容
                </button>
              </div>
            )}

            <div className={styles.previewHeaderActions}>
              {hasSkillMeta && (
                <button
                  type="button"
                  className={styles.panelAction}
                  style={{
                    width: "auto",
                    padding: "0 8px",
                    background: "rgba(168, 85, 247, 0.1)",
                    color: "#9333ea",
                  }}
                  onClick={() => handleImportSkill(artifactContent)}
                  title="直接导入此技能"
                >
                  <span style={{ fontSize: 12, fontWeight: 600 }}>
                    ✨ 导入技能
                  </span>
                </button>
              )}
              {isHtml && previewMode === "run" && (
                <>
                  <button
                    type="button"
                    className={styles.panelAction}
                    onClick={() => setIframeKey((k) => k + 1)}
                    title="重新加载预览"
                  >
                    <RefreshCw size={13} />
                  </button>
                  <button
                    type="button"
                    className={styles.panelAction}
                    onClick={() => {
                      const iframeUrl = getPreviewUrl(selectedArtifact);
                      window.open(iframeUrl, "_blank");
                    }}
                    title="在新窗口中打开"
                  >
                    <ExternalLink size={13} />
                  </button>
                </>
              )}
              {isMedia && (
                <button
                  type="button"
                  className={styles.panelAction}
                  onClick={() =>
                    window.open(getPreviewUrl(selectedArtifact), "_blank")
                  }
                  title="在新窗口中打开"
                >
                  <ExternalLink size={13} />
                </button>
              )}
              {!isTaskList && (
                <button
                  type="button"
                  className={styles.panelAction}
                  onClick={() => handleDownloadFile(selectedArtifact)}
                  title="下载文件"
                >
                  <Download size={13} />
                </button>
              )}
              <button
                type="button"
                className={styles.panelAction}
                onClick={() => setSelectedArtifact(null)}
                title="关闭预览"
              >
                ✕
              </button>
            </div>
          </div>

          <div className={styles.previewContent}>
            {artifactContentLoading ? (
              <div className={styles.previewLoading}>
                <Loader2
                  size={24}
                  className={`${styles.spinning}`}
                  style={{ color: "#2563eb" }}
                />
                <span style={{ marginTop: 8, fontSize: 12 }}>
                  Loading content...
                </span>
              </div>
            ) : isTaskList ? (
              renderTaskBoard()
            ) : isHtml && previewMode === "run" ? (
              <iframe
                key={iframeKey}
                src={getPreviewUrl(selectedArtifact, iframeKey)}
                className={styles.browserIframe}
                title="Live Artifact Preview"
                sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
                style={{ pointerEvents: isResizing ? "none" : "auto" }}
              />
            ) : isImage ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "100%",
                  height: "100%",
                  backgroundColor: "#f3f4f6",
                  padding: "16px",
                  boxSizing: "border-box",
                }}
              >
                <img
                  src={getPreviewUrl(selectedArtifact)}
                  alt={selectedArtifact}
                  style={{
                    maxWidth: "100%",
                    maxHeight: "100%",
                    objectFit: "contain",
                    borderRadius: "4px",
                    boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
                  }}
                />
              </div>
            ) : isMedia ? (
              renderMediaPreview(selectedArtifact)
            ) : isDownloadOnly ? (
              renderDownloadOnlyPreview(selectedArtifact)
            ) : (
              <pre className={styles.previewCode}>{artifactContent}</pre>
            )}
          </div>
        </>
      );
    }

    if (selectedFilePath) {
      const isHtml = isHtmlFile(selectedFilePath);
      const isImage = isImageFile(selectedFilePath);
      const isMedia = isMediaPreviewFile(selectedFilePath);
      const isDownloadOnly = isDownloadOnlyPreviewFile(selectedFilePath);
      const hasSkillMeta =
        rawFileContent &&
        /---[\s\S]*?name:\s*([^\r\n]+)[\s\S]*?---/i.test(rawFileContent);

      return (
        <>
          <div className={styles.previewHeader}>
            <span className={styles.previewFileName}>{selectedFilePath}</span>

            {isHtml && (
              <div className={styles.toggleGroup}>
                <button
                  type="button"
                  className={`${styles.toggleBtn} ${
                    previewMode === "run" ? styles.toggleBtnActive : ""
                  }`}
                  onClick={() => setPreviewMode("run")}
                >
                  <span className={styles.toggleIcon}>🎮</span> 运行预览
                </button>
                <button
                  type="button"
                  className={`${styles.toggleBtn} ${
                    previewMode === "code" ? styles.toggleBtnActive : ""
                  }`}
                  onClick={() => setPreviewMode("code")}
                >
                  <span className={styles.toggleIcon}>📝</span> 源码内容
                </button>
              </div>
            )}

            <div className={styles.previewHeaderActions}>
              {hasSkillMeta && (
                <button
                  type="button"
                  className={styles.panelAction}
                  style={{
                    width: "auto",
                    padding: "0 8px",
                    background: "rgba(168, 85, 247, 0.1)",
                    color: "#9333ea",
                  }}
                  onClick={() => handleImportSkill(rawFileContent)}
                  title="直接导入此技能"
                >
                  <span style={{ fontSize: 12, fontWeight: 600 }}>
                    ✨ 导入技能
                  </span>
                </button>
              )}
              {isHtml && previewMode === "run" && (
                <>
                  <button
                    type="button"
                    className={styles.panelAction}
                    onClick={() => setIframeKey((k) => k + 1)}
                    title="重新加载预览"
                  >
                    <RefreshCw size={13} />
                  </button>
                  <button
                    type="button"
                    className={styles.panelAction}
                    onClick={() => {
                      const iframeUrl = getPreviewUrl(selectedFilePath);
                      window.open(iframeUrl, "_blank");
                    }}
                    title="在新窗口中打开"
                  >
                    <ExternalLink size={13} />
                  </button>
                </>
              )}
              {isMedia && (
                <button
                  type="button"
                  className={styles.panelAction}
                  onClick={() =>
                    window.open(getPreviewUrl(selectedFilePath), "_blank")
                  }
                  title="在新窗口中打开"
                >
                  <ExternalLink size={13} />
                </button>
              )}
              <button
                type="button"
                className={styles.panelAction}
                onClick={() => handleDownloadFile(selectedFilePath)}
                title="下载文件"
              >
                <Download size={13} />
              </button>
              <button
                type="button"
                className={styles.panelAction}
                onClick={() => setSelectedFilePath(null)}
                title="关闭预览"
              >
                ✕
              </button>
            </div>
          </div>

          <div className={styles.previewContent}>
            {rawFileContentLoading ? (
              <div className={styles.previewLoading}>
                <Loader2
                  size={24}
                  className={`${styles.spinning}`}
                  style={{ color: "#2563eb" }}
                />
                <span style={{ marginTop: 8, fontSize: 12 }}>
                  Loading file...
                </span>
              </div>
            ) : isHtml && previewMode === "run" ? (
              <iframe
                key={iframeKey}
                src={getPreviewUrl(selectedFilePath, iframeKey)}
                className={styles.browserIframe}
                title="Live File Preview"
                sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
                style={{ pointerEvents: isResizing ? "none" : "auto" }}
              />
            ) : isImage ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "100%",
                  height: "100%",
                  backgroundColor: "#f3f4f6",
                  padding: "16px",
                  boxSizing: "border-box",
                }}
              >
                <img
                  src={getPreviewUrl(selectedFilePath)}
                  alt={selectedFilePath}
                  style={{
                    maxWidth: "100%",
                    maxHeight: "100%",
                    objectFit: "contain",
                    borderRadius: "4px",
                    boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
                  }}
                />
              </div>
            ) : isMedia ? (
              renderMediaPreview(selectedFilePath)
            ) : isDownloadOnly ? (
              renderDownloadOnlyPreview(selectedFilePath)
            ) : (
              <pre className={styles.previewCode}>{rawFileContent}</pre>
            )}
          </div>
        </>
      );
    }

    if (activeChangePath) {
      return (
        <>
          <div className={styles.previewHeader}>
            <span className={styles.previewFileName}>{activeChangePath}</span>
            <button
              type="button"
              className={styles.panelAction}
              onClick={() => setActiveChangePath(null)}
              title="关闭预览"
            >
              ✕
            </button>
          </div>
          <div className={styles.previewContent}>
            {renderDiffContent(activeDiffText)}
          </div>
        </>
      );
    }

    return null;
  };

  // ── Main Panel Layout ────────────────────────────────────────────

  return (
    <div
      className={`${styles.panel} ${hasPreview ? styles.panelExpanded : ""}`}
      style={{
        width: panelWidth,
        transition: isResizing ? "none" : undefined,
      }}
    >
      {/* Drag handle to resize panel */}
      <div className={styles.resizerHandle} onMouseDown={startResizing} />

      {/* Left Column: Navigation Section */}
      <div className={styles.leftColumn}>
        {/* Panel Top Header */}
        <div className={styles.panelHeader}>
          <div className={styles.panelTitle}>
            {activeTab === "artifacts" && <FileText size={16} />}
            {activeTab === "files" && <FolderOpen size={16} />}
            {activeTab === "changes" && <GitBranch size={16} />}
            {activeTab === "browser" && <Globe size={16} />}
            <span>
              {activeTab === "artifacts" && t("artifact.tab.artifacts", "产物")}
              {activeTab === "files" && t("artifact.tab.files", "全部文件")}
              {activeTab === "changes" && t("artifact.tab.changes", "代码变更")}
              {activeTab === "browser" &&
                t("artifact.tab.browser", "内置浏览器")}
            </span>
          </div>
          <div className={styles.panelActions}>
            {activeTab !== "browser" && (
              <button
                className={styles.panelAction}
                onClick={() => loadData(activeTab)}
                title={t("artifact.refresh", "刷新")}
              >
                <RefreshCw
                  size={14}
                  className={
                    artifactsLoading || filesLoading || changesLoading
                      ? styles.spinning
                      : ""
                  }
                />
              </button>
            )}
            {activeTab === "artifacts" && (
              <button
                className={styles.panelAction}
                onClick={handleDownloadArtifacts}
                title={t("artifact.download", "下载产物包")}
              >
                <Download size={14} />
              </button>
            )}
            <button
              className={styles.panelAction}
              onClick={onToggle}
              title={t("artifact.hide", "收起")}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>

        {/* Tabs Control Row */}
        <div className={styles.tabsRow}>
          <button
            className={`${styles.tabBtn} ${
              activeTab === "artifacts" ? styles.tabBtnActive : ""
            }`}
            onClick={() => setActiveTab("artifacts")}
          >
            {t("artifact.tab.artifacts", "产物")}
          </button>
          <button
            className={`${styles.tabBtn} ${
              activeTab === "files" ? styles.tabBtnActive : ""
            }`}
            onClick={() => setActiveTab("files")}
          >
            {t("artifact.tab.files", "文件")}
          </button>
          <button
            className={`${styles.tabBtn} ${
              activeTab === "changes" ? styles.tabBtnActive : ""
            }`}
            onClick={() => setActiveTab("changes")}
          >
            {t("artifact.tab.changes", "变更")}
            {changes.length > 0 && (
              <span className={styles.changesBadge}>{changes.length}</span>
            )}
          </button>
          <button
            className={`${styles.tabBtn} ${
              activeTab === "browser" ? styles.tabBtnActive : ""
            }`}
            onClick={() => setActiveTab("browser")}
          >
            {t("artifact.tab.browser", "浏览器")}
          </button>
        </div>

        {/* Main Tab Panels */}
        <div className={styles.tabContentArea}>
          {/* Tab 1: Artifacts (产物) */}
          {activeTab === "artifacts" && (
            <div className={styles.scrollContainer}>
              {artifactsLoading && (
                <div className={styles.tabLoading}>Loading artifacts...</div>
              )}
              {!artifactsLoading && artifacts.length === 0 && (
                <div className={styles.emptyState}>
                  <FileText size={32} strokeWidth={1} />
                  <span>{t("artifact.empty", "暂无产物文件")}</span>
                </div>
              )}
              {artifacts.map((file) => {
                const isVirtual = file.isVirtual;
                return (
                  <div
                    key={file.path}
                    className={`${styles.fileItem} ${
                      selectedArtifact === file.path
                        ? styles.fileItemActive
                        : ""
                    }`}
                    onClick={() => handlePreviewArtifact(file.path)}
                  >
                    <div
                      className={styles.fileIcon}
                      style={{
                        color: isVirtual
                          ? "#2563eb"
                          : getFileColor(file.filename),
                      }}
                    >
                      {isVirtual ? (
                        <ListTodo size={16} />
                      ) : (
                        getFileIcon(file.filename)
                      )}
                    </div>
                    <div className={styles.fileInfo}>
                      <div className={styles.fileName}>
                        {isVirtual ? "📋 任务列表" : file.filename}
                      </div>
                      <div className={styles.fileMeta}>
                        {isVirtual
                          ? "Visual Interactive Todo"
                          : `${formatFileSize(file.size)} · ${formatTime(
                              file.modified_time,
                            )}`}
                      </div>
                    </div>
                    <div className={styles.fileActions}>
                      {!isVirtual && (
                        <button
                          className={styles.fileAction}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDownloadFile(file.path);
                          }}
                          title="下载产物"
                        >
                          <Download size={13} />
                        </button>
                      )}
                      <button
                        className={styles.fileAction}
                        onClick={(e) => {
                          e.stopPropagation();
                          handlePreviewArtifact(file.path);
                        }}
                        title={t("artifact.preview", "预览")}
                      >
                        <Eye size={13} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Tab 2: All Files (全部文件) */}
          {activeTab === "files" && (
            <div className={styles.scrollContainer}>
              {filesLoading && (
                <div className={styles.tabLoading}>
                  Loading workspace tree...
                </div>
              )}
              {!filesLoading && fileTree.length === 0 && (
                <div className={styles.emptyState}>
                  <FolderOpen size={32} strokeWidth={1} />
                  <span>Empty workspace</span>
                </div>
              )}
              {fileTree.length > 0 && (
                <div className={styles.treeContainer}>
                  {renderFileTreeNodes(fileTree)}
                </div>
              )}
            </div>
          )}

          {/* Tab 3: Git Changes (变更) */}
          {activeTab === "changes" && (
            <div className={styles.scrollContainer}>
              {changesLoading && (
                <div className={styles.tabLoading}>
                  Checking local changes...
                </div>
              )}
              {!changesLoading && changes.length === 0 && (
                <div className={styles.emptyState}>
                  <GitBranch size={32} strokeWidth={1} />
                  <span>{t("artifact.changes.empty", "暂无代码变更")}</span>
                </div>
              )}
              {changes.map((item) => (
                <div
                  key={item.filepath}
                  className={`${styles.fileItem} ${
                    activeChangePath === item.filepath
                      ? styles.fileItemActive
                      : ""
                  }`}
                  onClick={() => handleSelectChange(item)}
                >
                  <div className={styles.fileIcon} style={{ color: "#3b82f6" }}>
                    <FileCode size={16} />
                  </div>
                  <div className={styles.fileInfo}>
                    <div className={styles.fileName}>{item.filepath}</div>
                    <div className={styles.fileMeta}>Git workspace change</div>
                  </div>
                  <span
                    className={`${styles.statusBadge} ${
                      item.status === "A" || item.status === "??"
                        ? styles.statusAdd
                        : item.status === "D"
                        ? styles.statusDel
                        : styles.statusMod
                    }`}
                  >
                    {item.status || "M"}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Tab 4: Local Preview Browser (内置浏览器) */}
          {activeTab === "browser" && (
            <div className={styles.browserContainer}>
              {/* Address Bar */}
              <form
                onSubmit={handleBrowserNavigate}
                className={styles.browserAddressBar}
              >
                <Globe size={14} className={styles.addressGlobeIcon} />
                <input
                  type="text"
                  className={styles.addressInput}
                  value={browserInput}
                  onChange={(e) => setBrowserInput(e.target.value)}
                  placeholder="Relative file path, e.g. index.html"
                />
                <div className={styles.addressActions}>
                  <button
                    type="button"
                    onClick={handleBrowserRefresh}
                    className={styles.addressBtn}
                    title="刷新预览"
                  >
                    <RefreshCw size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={handleBrowserOpenExternal}
                    className={styles.addressBtn}
                    title="在新窗口打开"
                  >
                    <ExternalLink size={13} />
                  </button>
                </div>
              </form>

              {/* Iframe View */}
              <div className={styles.iframeWrapper}>
                <iframe
                  key={iframeKey}
                  src={getPreviewUrl(previewPath, iframeKey)}
                  className={styles.browserIframe}
                  title="Workspace App Preview"
                  sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
                  style={{ pointerEvents: isResizing ? "none" : "auto" }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right Column: Full-Height Interactive Preview Engine */}
      {hasPreview && (
        <div className={styles.rightColumn}>{renderPreviewEngine()}</div>
      )}
    </div>
  );
}
