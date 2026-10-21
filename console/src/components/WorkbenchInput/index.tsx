import React, {
  useRef,
  useState,
  useEffect,
  useCallback,
  useLayoutEffect,
} from "react";
import { useTranslation } from "react-i18next";
import { AtSign, Paperclip, Send, Mic, X, FileText } from "lucide-react";
import { message } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { useLocation } from "react-router-dom";
import ChatToolbar from "../../pages/Chat/components/ChatToolbar";
import {
  getSkillInvocationName,
  type ToolbarSkillItem,
} from "../../pages/Chat/components/skillToolbarModel";
import {
  ensureSkillInstalledForAgent,
  resolveSkillInstallAgentId,
} from "../../pages/Chat/utils/skillTargetInstall";
import { useAgentStore, type ActiveMode } from "../../stores/agentStore";
import { workspaceApi } from "../../api/modules/workspace";
import { chatApi } from "../../api/modules/chat";
import { agentsApi } from "../../api/modules/agents";
import {
  RealtimeSpeechController,
  type RealtimeSpeechState,
} from "../../features/realtimeSpeech/RealtimeSpeechController";
import { resizeTextareaToContent } from "../../utils/textareaAutosize";
import { getRouteChatId } from "../../pages/Chat/routeSession";
import {
  isDesktopRuntime,
  readDesktopClipboardFiles,
} from "../../utils/desktopClipboard";
import styles from "./index.module.less";

// ── Types ─────────────────────────────────────────────────────────
interface WorkbenchInputProps {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  isClawMode?: boolean;
  isGenerating?: boolean;
  topAccessory?: React.ReactNode;
  inFlow?: boolean;
  wide?: boolean;
  onStop?: () => void;
  onSkillSelect?: (skill: ToolbarSkillItem) => void;
  // Controlled overrides for task-specific mode
  overrideSelectedAgent?: string;
  overrideActiveMode?: string;
  onAgentChange?: (agentId: string) => void;
  onModeChange?: (mode: string) => void;
}

interface UploadedFile {
  id: string;
  name: string;
  url: string;
  uploading: boolean;
}

interface WorkspaceFileNode {
  name: string;
  path: string;
  isDir?: boolean;
  children?: WorkspaceFileNode[];
}

// ── Constants & Helpers ──────────────────────────────────────────
const CHAT_ATTACHMENT_MAX_MB = 25;

const createUploadId = (file: File) =>
  `${file.name}-${file.size}-${file.lastModified}-${
    globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2)
  }`;

const hasDraggedFiles = (event: React.DragEvent<HTMLElement>) =>
  Array.from(event.dataTransfer.types || []).includes("Files");

const getClipboardFiles = (event: React.ClipboardEvent<HTMLElement>) => {
  const itemFiles = Array.from(event.clipboardData.items || [])
    .filter((item) => item.kind === "file")
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null);
  return itemFiles.length > 0
    ? itemFiles
    : Array.from(event.clipboardData.files || []);
};

const normalizeActiveMode = (mode?: string): ActiveMode | undefined => {
  if (mode === "craft" || mode === "plan" || mode === "ask" || mode === "") {
    return mode;
  }
  return undefined;
};

const joinSpeechText = (prefix: string, transcript: string) => {
  if (!prefix || !transcript) return `${prefix}${transcript}`;
  if (/\s$/.test(prefix)) return `${prefix}${transcript}`;
  const bothChinese =
    /[\u3400-\u9fff]$/.test(prefix) && /^[\u3400-\u9fff]/.test(transcript);
  return `${prefix}${bothChinese ? "" : " "}${transcript}`;
};

// Speech wave animation for premium look
const RecordingIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 1000 1000"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{
      color: "#ef4444",
      height: "1.2em",
      width: "1.2em",
      verticalAlign: "middle",
    }}
  >
    <title>Speech Recording</title>
    {Array.from({ length: 4 }).map((_, index) => {
      const dest = (1000 - 140 * 4) / 3;
      const x = index * (dest + 140);
      const yMin = 500 - 250 / 2;
      const yMax = 500 - 500 / 2;

      return (
        <rect
          fill="currentColor"
          rx={70}
          ry={70}
          height={250}
          width={140}
          x={x}
          y={yMin}
          key={index}
        >
          <animate
            attributeName="height"
            values="250; 500; 250"
            keyTimes="0; 0.5; 1"
            dur="0.8s"
            begin={`${(0.8 / 4) * index}s`}
            repeatCount="indefinite"
          />
          <animate
            attributeName="y"
            values={`${yMin}; ${yMax}; ${yMin}`}
            keyTimes="0; 0.5; 1"
            dur="0.8s"
            begin={`${(0.8 / 4) * index}s`}
            repeatCount="indefinite"
          />
        </rect>
      );
    })}
  </svg>
);

export default function WorkbenchInput({
  onSubmit,
  disabled,
  isClawMode = false,
  isGenerating = false,
  topAccessory,
  inFlow = false,
  wide = false,
  onStop,
  overrideSelectedAgent,
  overrideActiveMode,
  onAgentChange,
  onModeChange,
}: WorkbenchInputProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const chatId = React.useMemo(
    () => getRouteChatId(location.pathname),
    [location.pathname],
  );
  const [customInputValue, setCustomInputValue] = useState("");
  const customInputRef = useRef<HTMLTextAreaElement>(null);

  // Store hook
  const {
    clawSelectedAgent,
    selectedAgent: storeSelectedAgent,
    selectedExpertTeam,
    setAgents,
  } = useAgentStore();

  // Local state for selected skill (to ensure isolation between claw, task, etc.)
  const [selectedSkill, setSelectedSkill] = useState<ToolbarSkillItem | null>(
    null,
  );

  // ── States for @ Mentions (Agents) ───────────────────────────────

  // ── States for Attachments ──────────────────────────────────────
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);

  useEffect(() => {
    const resetDrag = () => {
      dragDepthRef.current = 0;
      setIsDraggingFiles(false);
    };
    const cancelDrag = (event: KeyboardEvent) => {
      if (event.key === "Escape") resetDrag();
    };
    window.addEventListener("dragend", resetDrag);
    window.addEventListener("drop", resetDrag);
    window.addEventListener("blur", resetDrag);
    window.addEventListener("keydown", cancelDrag);
    return () => {
      window.removeEventListener("dragend", resetDrag);
      window.removeEventListener("drop", resetDrag);
      window.removeEventListener("blur", resetDrag);
      window.removeEventListener("keydown", cancelDrag);
    };
  }, []);

  // ── States for @ File Mentions ───────────────────────────────
  const [workspaceFiles, setWorkspaceFiles] = useState<
    { name: string; path: string }[]
  >([]);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionedFiles, setMentionedFiles] = useState<string[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isFetchingFiles, setIsFetchingFiles] = useState(false);
  const [isInjectingContext, setIsInjectingContext] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const mentionPopupRef = useRef<HTMLDivElement>(null);

  const filteredFiles = React.useMemo(() => {
    if (mentionQuery === null) return [];
    const query = mentionQuery.toLowerCase();
    return workspaceFiles
      .filter(
        (f) =>
          f.name.toLowerCase().includes(query) ||
          f.path.toLowerCase().includes(query),
      )
      .slice(0, 8); // Top 8 results
  }, [mentionQuery, workspaceFiles]);

  // Reset selected index when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [mentionQuery]);

  // ── States for Voice Recording ──────────────────────────────────
  const [speechState, setSpeechState] = useState<RealtimeSpeechState>("idle");
  const speechControllerRef = useRef<RealtimeSpeechController | null>(null);
  const speechPrefixRef = useRef("");

  // ── Fetch Agents for @ Mentions ─────────────────────────────────
  const fetchAgents = useCallback(async () => {
    try {
      const data = await agentsApi.listAgents();
      // Sort agents: enabled first, disabled last
      const sortedAgents = [...data.agents].sort((a, b) => {
        if (a.enabled === b.enabled) return 0;
        return a.enabled ? -1 : 1;
      });
      setAgents(sortedAgents);
    } catch (err) {
      console.error("Failed to load agents in input:", err);
    }
  }, [setAgents]);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  useLayoutEffect(() => {
    resizeTextareaToContent(customInputRef.current, 220);
  }, [customInputValue]);

  // ── File Upload Handlers ────────────────────────────────────────
  const handleAttachClick = () => {
    if (disabled) return;
    fileInputRef.current?.click();
  };

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      // Create temp uploading card placeholders
      const newFiles: UploadedFile[] = files.map((file) => ({
        id: createUploadId(file),
        name: file.name,
        url: "",
        uploading: true,
      }));
      setUploadedFiles((prev) => [...prev, ...newFiles]);

      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const uploadEntry = newFiles[index];
        const sizeMb = file.size / 1024 / 1024;
        if (sizeMb > CHAT_ATTACHMENT_MAX_MB) {
          message.error(
            t(
              "chat.attachment.fileTooLarge",
              `文件 ${file.name} 超过 ${CHAT_ATTACHMENT_MAX_MB}MB 限制`,
            ),
          );
          // Remove the oversized file from lists
          setUploadedFiles((prev) =>
            prev.filter((f) => f.id !== uploadEntry.id),
          );
          continue;
        }

        try {
          const res = await chatApi.uploadFile(file);
          setUploadedFiles((prev) =>
            prev.map((f) =>
              f.id === uploadEntry.id
                ? { ...f, url: res.url, uploading: false }
                : f,
            ),
          );
        } catch (err) {
          console.error("Upload error:", err);
          message.error(
            t("chat.attachment.uploadFailed", `文件 ${file.name} 上传失败`),
          );
          // Remove failed upload
          setUploadedFiles((prev) =>
            prev.filter((f) => f.id !== uploadEntry.id),
          );
        }
      }
    },
    [t],
  );

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    await uploadFiles(files);

    // Reset input to allow choosing the same file name later
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDeleteAttachment = (fileId: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.id !== fileId));
  };

  const handlePaste = useCallback(
    async (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
      if (disabled) return;
      const webFiles = getClipboardFiles(event);
      if (webFiles.length > 0) {
        event.preventDefault();
        void uploadFiles(webFiles);
        return;
      }

      if (!isDesktopRuntime()) return;

      const textarea = event.currentTarget;
      const selectionStart = textarea.selectionStart ?? textarea.value.length;
      const selectionEnd = textarea.selectionEnd ?? selectionStart;
      const pastedText = event.clipboardData.getData?.("text/plain") ?? "";
      event.preventDefault();
      try {
        const nativeFiles = await readDesktopClipboardFiles();
        if (nativeFiles.length > 0) {
          void uploadFiles(nativeFiles);
          return;
        }
      } catch (error) {
        console.warn("Unable to read desktop clipboard attachments:", error);
      }

      if (!pastedText) return;
      setCustomInputValue(
        (currentValue) =>
          `${currentValue.slice(
            0,
            selectionStart,
          )}${pastedText}${currentValue.slice(selectionEnd)}`,
      );
      requestAnimationFrame(() => {
        const nextPosition = selectionStart + pastedText.length;
        textarea.focus();
        textarea.setSelectionRange(nextPosition, nextPosition);
      });
    },
    [disabled, uploadFiles],
  );

  const handleDragEnter = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (disabled || !hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current += 1;
      setIsDraggingFiles(true);
    },
    [disabled],
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (disabled || !hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      setIsDraggingFiles(true);
    },
    [disabled],
  );

  const handleDragLeave = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (!hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
      if (dragDepthRef.current === 0) {
        setIsDraggingFiles(false);
      }
    },
    [],
  );

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (!hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current = 0;
      setIsDraggingFiles(false);
      if (disabled) return;
      void uploadFiles(Array.from(event.dataTransfer.files || []));
    },
    [disabled, uploadFiles],
  );

  // ── Realtime Voice Input ────────────────────────────────────────
  useEffect(() => {
    const controller = new RealtimeSpeechController({
      onTranscript: (text) => {
        setCustomInputValue(joinSpeechText(speechPrefixRef.current, text));
      },
      onStateChange: setSpeechState,
      onError: (errorMessage) => message.error(errorMessage),
    });
    speechControllerRef.current = controller;
    return () => {
      controller.destroy();
      speechControllerRef.current = null;
    };
  }, []);

  const toggleRecording = useCallback(() => {
    if (disabled) return;
    const controller = speechControllerRef.current;
    if (!controller) return;
    if (speechState === "idle") {
      speechPrefixRef.current = customInputValue;
      void controller.start();
    } else if (speechState !== "processing") {
      controller.stop();
    }
  }, [customInputValue, disabled, speechState]);

  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const isM = e.key === "m" || e.key === "M";
      const hasCtrlOrMeta = e.ctrlKey || e.metaKey;
      if (hasCtrlOrMeta && e.shiftKey && isM) {
        e.preventDefault();
        toggleRecording();
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => {
      window.removeEventListener("keydown", handleGlobalKeyDown);
    };
  }, [toggleRecording]);

  // ── Custom Send Handlers ────────────────────────────────────────
  const handleCustomSend = async () => {
    if (disabled || isInjectingContext || isSubmitting) return;
    setIsSubmitting(true);

    let textToSend = customInputValue.trim();

    // Check if there are any uploading files
    const stillUploading = uploadedFiles.some((f) => f.uploading);
    if (stillUploading) {
      message.warning(
        t("chat.attachment.stillUploading", "附件还在上传中，请稍候"),
      );
      setIsSubmitting(false);
      return;
    }

    // Append completed attachments as Markdown links
    const completedFiles = uploadedFiles.filter((f) => !f.uploading && f.url);
    if (completedFiles.length > 0) {
      const attachmentsMarkdown = completedFiles
        .map((f) => `📎 [${f.name}](${f.url})`)
        .join("\n");
      textToSend = textToSend
        ? `${textToSend}\n\n${attachmentsMarkdown}`
        : attachmentsMarkdown;
    }

    if (mentionedFiles.length > 0) {
      setIsInjectingContext(true);
      try {
        let injectedContext = "";
        for (const path of mentionedFiles) {
          try {
            const res = await workspaceApi.loadRawFile(path, chatId);
            injectedContext += `\n\n<file_context path="${path}">\n${res.content}\n</file_context>`;
          } catch (err) {
            console.error("Failed to load mentioned file context:", err);
            message.warning(
              t("chat.mention.loadFailed", `无法加载文件 ${path} 的内容`),
            );
          }
        }
        textToSend = textToSend
          ? `${textToSend}${injectedContext}`
          : injectedContext;
      } finally {
        setIsInjectingContext(false);
      }
    }

    // If a skill is selected, prepend the invocation command
    if (selectedSkill) {
      const targetAgentId = resolveSkillInstallAgentId({
        selectedAgent:
          overrideSelectedAgent ||
          (isClawMode ? clawSelectedAgent : storeSelectedAgent),
        expertTeam: isClawMode ? null : selectedExpertTeam,
      });
      try {
        await ensureSkillInstalledForAgent(selectedSkill, targetAgentId);
      } catch (error) {
        console.error(
          "Failed to prepare selected skill for target agent",
          error,
        );
        message.error("技能安装失败，请稍后重试");
        setIsSubmitting(false);
        return;
      }

      textToSend = `/[${getSkillInvocationName(
        selectedSkill,
      )}]\n\n${textToSend}`;
    }

    if (!textToSend.trim()) {
      setIsSubmitting(false);
      return;
    }

    onSubmit(textToSend);
    setCustomInputValue("");
    setUploadedFiles([]); // Clear uploaded files list
    setMentionedFiles([]); // Clear mentions
    setSelectedSkill(null); // Clear selected skill

    // Release submitting lock after a short delay
    setTimeout(() => setIsSubmitting(false), 500);
  };

  const handleCustomChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setCustomInputValue(value);

    // Check for @ mention trigger at the cursor position
    const cursorPosition = e.target.selectionStart;
    const textBeforeCursor = value.substring(0, cursorPosition);
    // Match "@query" where query doesn't contain spaces
    const match = textBeforeCursor.match(/(^|\s)@([^\s]*)$/);

    if (match) {
      const query = match[2];
      setMentionQuery(query);
      if (workspaceFiles.length === 0 && !isFetchingFiles) {
        setIsFetchingFiles(true);
        workspaceApi
          .listAllFiles(chatId)
          .then((tree) => {
            const flatFiles: { name: string; path: string }[] = [];
            const flatten = (nodes: WorkspaceFileNode[]) => {
              for (const node of nodes) {
                if (node.isDir) {
                  if (node.children) flatten(node.children);
                } else {
                  flatFiles.push({ name: node.name, path: node.path });
                }
              }
            };
            flatten(tree);
            setWorkspaceFiles(flatFiles);
          })
          .finally(() => setIsFetchingFiles(false));
      }
    } else {
      setMentionQuery(null);
    }
  };

  const handleSelectMentionFile = (path: string) => {
    if (!mentionedFiles.includes(path)) {
      setMentionedFiles((prev) => [...prev, path]);
    }
    const cursorPosition = customInputRef.current?.selectionStart || 0;
    const textBeforeCursor = customInputValue.substring(0, cursorPosition);
    const textAfterCursor = customInputValue.substring(cursorPosition);

    const newTextBeforeCursor = textBeforeCursor.replace(
      /(^|\s)@[^\s]*$/,
      "$1",
    );
    setCustomInputValue(newTextBeforeCursor + textAfterCursor);
    setMentionQuery(null);

    setTimeout(() => {
      if (customInputRef.current) {
        customInputRef.current.focus();
        customInputRef.current.selectionStart = newTextBeforeCursor.length;
        customInputRef.current.selectionEnd = newTextBeforeCursor.length;
      }
    }, 0);
  };

  const handleCustomKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionQuery !== null) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) =>
          Math.min(prev + 1, filteredFiles.length - 1),
        );
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (filteredFiles[selectedIndex]) {
          handleSelectMentionFile(filteredFiles[selectedIndex].path);
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionQuery(null);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      if (e.nativeEvent.isComposing) return;
      if (!e.defaultPrevented) {
        e.preventDefault();
        handleCustomSend();
      }
    }
  };

  return (
    <div
      className={`${styles.chatToolbarWrapper} ${
        inFlow ? styles.inFlow : ""
      } ${wide ? styles.wide : ""}`}
    >
      {topAccessory && (
        <div className={styles.inputTopAccessory}>{topAccessory}</div>
      )}
      {disabled ? (
        <div className={styles.disabledNotice} role="status">
          请先完成上方交互卡片，提交后即可继续输入
        </div>
      ) : null}
      <div
        className={`${styles.inputArea} ${
          isDraggingFiles ? styles.inputAreaDragging : ""
        }`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {isDraggingFiles && !disabled && (
          <div className={styles.dropOverlay} role="status" aria-live="polite">
            <Paperclip size={18} />
            <span>{t("workbench.input.dropFiles", "松开即可上传附件")}</span>
          </div>
        )}
        {/* Uploaded Attachments & Mentions Preview Section */}
        {(uploadedFiles.length > 0 || mentionedFiles.length > 0) && (
          <div className={styles.attachmentsArea}>
            {uploadedFiles.map((file, idx) => (
              <div
                key={file.id || `upload-${file.name}-${idx}`}
                className={styles.attachmentCard}
              >
                {file.uploading ? (
                  <LoadingOutlined style={{ fontSize: 14, color: "#1890ff" }} />
                ) : (
                  <FileText size={14} style={{ color: "#2563eb" }} />
                )}
                <span className={styles.attachmentName} title={file.name}>
                  {file.name}
                </span>
                {!file.uploading && (
                  <button
                    className={styles.attachmentDeleteBtn}
                    onClick={() => handleDeleteAttachment(file.id)}
                    title={t("common.delete", "删除")}
                  >
                    <X size={10} />
                  </button>
                )}
              </div>
            ))}

            {mentionedFiles.map((path, idx) => {
              const name = path.split("/").pop() || path;
              return (
                <div
                  key={`mention-${idx}`}
                  className={styles.attachmentCard}
                  style={{
                    background: "rgba(16, 185, 129, 0.1)",
                    border: "1px solid rgba(16, 185, 129, 0.2)",
                  }}
                >
                  <FileText size={14} style={{ color: "#10b981" }} />
                  <span className={styles.attachmentName} title={path}>
                    {name}
                  </span>
                  <button
                    className={styles.attachmentDeleteBtn}
                    onClick={() =>
                      setMentionedFiles((prev) =>
                        prev.filter((p) => p !== path),
                      )
                    }
                    title={t("common.delete", "删除")}
                  >
                    <X size={10} />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* Mention File Popup */}
        {mentionQuery !== null && (
          <div className={styles.mentionPopupWrapper}>
            <div className={styles.mentionPopupList} ref={mentionPopupRef}>
              <div className={styles.mentionHeader}>
                <FileText size={14} /> 添加文件作为回答背景
              </div>
              {isFetchingFiles ? (
                <div className={styles.mentionLoading}>
                  <LoadingOutlined /> 正在加载工作区文件...
                </div>
              ) : filteredFiles.length === 0 ? (
                <div className={styles.mentionEmpty}>未找到匹配文件</div>
              ) : (
                filteredFiles.map((file, idx) => (
                  <div
                    key={file.path}
                    className={`${styles.mentionItem} ${
                      idx === selectedIndex ? styles.mentionItemSelected : ""
                    }`}
                    onClick={() => handleSelectMentionFile(file.path)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <FileText size={14} className={styles.mentionItemIcon} />
                    <span className={styles.mentionItemName}>{file.name}</span>
                    <span className={styles.mentionItemPath}>{file.path}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Selected Skill Pill Preview */}
        {selectedSkill && (
          <div className={styles.selectedSkillPill}>
            <span
              className={styles.skillPillIcon}
              style={{ background: selectedSkill.color, color: "#fff" }}
            >
              {selectedSkill.icon}
            </span>
            <span className={styles.skillPillName}>{selectedSkill.name}</span>
            <X
              size={12}
              className={styles.skillPillClose}
              onClick={() => setSelectedSkill(null)}
            />
          </div>
        )}

        <textarea
          ref={customInputRef}
          className={styles.inputField}
          placeholder={t("workbench.inputPlaceholder", "描述你想完成的任务...")}
          value={customInputValue}
          onChange={handleCustomChange}
          onKeyDown={handleCustomKeyDown}
          onPaste={handlePaste}
          rows={2}
          disabled={disabled || speechState !== "idle"}
        />

        <div className={styles.inputFooter}>
          <div className={styles.footerLeftWrapper}>
            <ChatToolbar
              disabled={disabled}
              isClawMode={isClawMode}
              onSkillSelect={(skill) => {
                setSelectedSkill(skill);
                customInputRef.current?.focus();
              }}
              overrideSelectedAgent={overrideSelectedAgent}
              overrideActiveMode={normalizeActiveMode(overrideActiveMode)}
              onAgentChange={onAgentChange}
              onModeChange={onModeChange}
            />
            <div className={styles.footerUtilityActions}>
              <button
                className={styles.toolbarBtn}
                title="添加文件作为回答背景"
                disabled={disabled}
                onClick={(e) => {
                  if (disabled) return;
                  e.preventDefault();
                  setMentionQuery("");
                  if (workspaceFiles.length === 0 && !isFetchingFiles) {
                    setIsFetchingFiles(true);
                    workspaceApi
                      .listAllFiles(chatId)
                      .then((tree) => {
                        const flatFiles: { name: string; path: string }[] = [];
                        const flatten = (nodes: WorkspaceFileNode[]) => {
                          for (const node of nodes) {
                            if (node.isDir) {
                              if (node.children) flatten(node.children);
                            } else {
                              flatFiles.push({
                                name: node.name,
                                path: node.path,
                              });
                            }
                          }
                        };
                        flatten(tree);
                        setWorkspaceFiles(flatFiles);
                      })
                      .finally(() => setIsFetchingFiles(false));
                  }
                  if (customInputRef.current) {
                    customInputRef.current.focus();
                    if (!customInputValue.endsWith("@")) {
                      const spacing =
                        customInputValue && !customInputValue.endsWith(" ")
                          ? " "
                          : "";
                      setCustomInputValue((prev) => prev + spacing + "@");
                    }
                  }
                }}
              >
                <AtSign size={16} />
              </button>
              <button
                className={styles.toolbarBtn}
                title={t("workbench.input.attachFile", "添加附件")}
                disabled={disabled}
                onClick={handleAttachClick}
              >
                <Paperclip size={16} />
              </button>
              <input
                type="file"
                ref={fileInputRef}
                multiple
                disabled={disabled}
                style={{ display: "none" }}
                onChange={handleFileChange}
              />
            </div>
          </div>

          <div className={styles.footerRight}>
            <button
              className={`${styles.footerAction} ${
                speechState === "recording" ? styles.voiceRecordingActive : ""
              }`}
              onClick={toggleRecording}
              disabled={speechState === "processing" || disabled}
              aria-label={
                speechState === "idle"
                  ? t("workbench.startSpeech", "开始语音输入")
                  : t("workbench.stopSpeech", "停止语音输入")
              }
              aria-pressed={speechState !== "idle"}
              title={
                speechState === "idle"
                  ? t("workbench.startSpeech", "开始语音输入")
                  : t("workbench.stopSpeech", "停止语音输入")
              }
            >
              {speechState === "connecting" || speechState === "processing" ? (
                <LoadingOutlined style={{ fontSize: 14 }} />
              ) : speechState === "recording" ? (
                <RecordingIcon />
              ) : (
                <Mic size={14} />
              )}
            </button>

            <button
              className={`${styles.sendBtn} ${
                isGenerating ? styles.stopBtnActive : ""
              }`}
              disabled={
                (isGenerating
                  ? false
                  : !customInputValue.trim() &&
                    uploadedFiles.length === 0 &&
                    mentionedFiles.length === 0) ||
                (!isGenerating && disabled) ||
                isInjectingContext ||
                speechState !== "idle"
              }
              onClick={isGenerating ? onStop : handleCustomSend}
              title={
                isGenerating
                  ? t("chat.stopGenerating", "停止生成")
                  : t("chat.send", "发送")
              }
            >
              {isGenerating ? (
                <div className={styles.stopIconWrapper}>
                  <div className={styles.stopIconInner} />
                </div>
              ) : isInjectingContext ? (
                <LoadingOutlined />
              ) : (
                <Send size={16} />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
