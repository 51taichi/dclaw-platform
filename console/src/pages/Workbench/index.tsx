import {
  useState,
  useRef,
  useEffect,
  useCallback,
  useLayoutEffect,
} from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { message } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import api from "../../api";
import { chatApi } from "../../api/modules/chat";
import { expertTeamsApi } from "../../api/modules/expertTeams";
import type { ExpertTeamTemplate } from "../../api/types/expertTeams";
import { useAgentStore } from "../../stores/agentStore";
import type { ActiveMode } from "../../stores/agentStore";
import ChatToolbar from "../Chat/components/ChatToolbar";
import { getSkillInvocationName } from "../Chat/components/skillToolbarModel";
import {
  ensureSkillInstalledForAgent,
  resolveSkillInstallAgentId,
} from "../Chat/utils/skillTargetInstall";
import { buildWorkbenchPrompt } from "./promptTemplates";
import { resizeTextareaToContent } from "../../utils/textareaAutosize";
import { savePendingTaskIntent } from "../../utils/pendingTaskIntent";
import {
  RealtimeSpeechController,
  type RealtimeSpeechState,
} from "../../features/realtimeSpeech/RealtimeSpeechController";
import {
  FileText,
  TrendingUp,
  BarChart3,
  Search,
  Package,
  Presentation,
  Palette,
  Mail,
  Code,
  Globe,
  Bot,
  Wrench,
  GitBranch,
  BookOpen,
  AtSign,
  Paperclip,
  Send,
  Mic,
  Square,
  Monitor,
  X,
} from "lucide-react";
import styles from "./index.module.less";

interface SceneConfig {
  key: string;
  label: string;
  icon: React.ReactNode;
  tags: Array<{
    key: string;
    label: string;
    icon: React.ReactNode;
  }>;
}

interface WorkbenchRouteState {
  initialPrompt?: string;
  selectedAgent?: string;
  activeMode?: ActiveMode;
  selectedExpertTeam?: string | ExpertTeamTemplate | null;
}

interface UploadedFile {
  id: string;
  name: string;
  url: string;
  uploading: boolean;
}

const CHAT_ATTACHMENT_MAX_MB = 25;

const createUploadId = (file: File) =>
  `${file.name}-${file.size}-${file.lastModified}-${
    globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2)
  }`;

const hasDraggedFiles = (event: React.DragEvent<HTMLElement>) =>
  Array.from(event.dataTransfer.types || []).includes("Files");

const joinSpeechText = (prefix: string, transcript: string) => {
  if (!prefix || !transcript) return `${prefix}${transcript}`;
  if (/\s$/.test(prefix)) return `${prefix}${transcript}`;
  const bothChinese =
    /[\u3400-\u9fff]$/.test(prefix) && /^[\u3400-\u9fff]/.test(transcript);
  return `${prefix}${bothChinese ? "" : " "}${transcript}`;
};

export default function WorkbenchPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeScene, setActiveScene] = useState("office");
  const [inputValue, setInputValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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

  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [speechState, setSpeechState] = useState<RealtimeSpeechState>("idle");
  const speechControllerRef = useRef<RealtimeSpeechController | null>(null);
  const speechPrefixRef = useRef("");

  useEffect(() => {
    const controller = new RealtimeSpeechController({
      onTranscript: (text) => {
        setInputValue(joinSpeechText(speechPrefixRef.current, text));
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

  const handleSpeechToggle = useCallback(() => {
    const controller = speechControllerRef.current;
    if (!controller) return;
    if (speechState === "idle") {
      speechPrefixRef.current = inputValue;
      void controller.start();
    } else if (speechState !== "processing") {
      controller.stop();
    }
  }, [inputValue, speechState]);

  const scenes: SceneConfig[] = [
    {
      key: "code",
      label: t("workbench.tabCode"),
      icon: <Code size={14} />,
      tags: [
        { key: "dev", label: t("workbench.tagDev"), icon: <Code size={14} /> },
        {
          key: "website",
          label: t("workbench.tagWebsite"),
          icon: <Globe size={14} />,
        },
        {
          key: "agent",
          label: t("workbench.tagAgent"),
          icon: <Bot size={14} />,
        },
        {
          key: "skillDev",
          label: t("workbench.tagSkillDev"),
          icon: <Wrench size={14} />,
        },
        {
          key: "cicd",
          label: t("workbench.tagCICD"),
          icon: <GitBranch size={14} />,
        },
        {
          key: "docs",
          label: t("workbench.tagDocs"),
          icon: <BookOpen size={14} />,
        },
      ],
    },
    {
      key: "office",
      label: t("workbench.tabOffice"),
      icon: <Monitor size={14} />,
      tags: [
        {
          key: "doc",
          label: t("workbench.tagDoc"),
          icon: <FileText size={14} />,
        },
        {
          key: "finance",
          label: t("workbench.tagFinance"),
          icon: <TrendingUp size={14} />,
        },
        {
          key: "data",
          label: t("workbench.tagData"),
          icon: <BarChart3 size={14} />,
        },
        {
          key: "research",
          label: t("workbench.tagResearch"),
          icon: <Search size={14} />,
        },
        {
          key: "product",
          label: t("workbench.tagProduct"),
          icon: <Package size={14} />,
        },
        {
          key: "slides",
          label: t("workbench.tagSlides"),
          icon: <Presentation size={14} />,
        },
        {
          key: "design",
          label: t("workbench.tagDesign"),
          icon: <Palette size={14} />,
        },
        {
          key: "email",
          label: t("workbench.tagEmail"),
          icon: <Mail size={14} />,
        },
      ],
    },
  ];

  const currentScene = scenes.find((s) => s.key === activeScene) || scenes[1];

  const [sending, setSending] = useState(false);
  const {
    selectedAgent,
    setSelectedAgent,
    selectedSkill,
    setSelectedSkill,
    activeMode,
    setActiveMode,
    selectedExpertTeam,
    setSelectedExpertTeam,
  } = useAgentStore();

  const hasInitialized = useRef(false);

  // Read initial state from routing (e.g. from Explore page or Experts page)
  useEffect(() => {
    if (hasInitialized.current) return;
    hasInitialized.current = true;

    const state = location.state as WorkbenchRouteState | null;
    const selectedExpertTeamState = state?.selectedExpertTeam;
    const hasRouteState = Boolean(
      state &&
        (state.initialPrompt ||
          state.selectedAgent ||
          state.activeMode !== undefined ||
          selectedExpertTeamState !== undefined),
    );

    // Check if state actually contains valid initialization data
    if (hasRouteState && state) {
      const cachedTeam = useAgentStore.getState().selectedExpertTeam;

      if (state.initialPrompt) {
        setInputValue(state.initialPrompt);
      }
      if (state.selectedAgent) {
        setSelectedAgent(state.selectedAgent);
      }
      if (state.activeMode !== undefined) {
        setActiveMode(state.activeMode);
      }

      if (selectedExpertTeamState) {
        if (typeof selectedExpertTeamState === "string") {
          if (cachedTeam?.id === selectedExpertTeamState) {
            setSelectedExpertTeam(cachedTeam);
          } else {
            expertTeamsApi
              .getExpertTeam(selectedExpertTeamState)
              .then((team) => setSelectedExpertTeam(team))
              .catch((error) => {
                console.error("Failed to restore expert team selection", error);
              });
          }
        } else {
          setSelectedExpertTeam(selectedExpertTeamState);
        }
      }
      // Clear state so it doesn't trigger again on reload
      navigate(location.pathname, { replace: true });
    } else {
      // Reset options to default values on normal entry
      setSelectedAgent("default");
      setActiveMode("craft");
      setSelectedSkill(null);
    }
    // Empty dependency array ensures it only runs on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      const nextFiles: UploadedFile[] = files.map((file) => ({
        id: createUploadId(file),
        name: file.name,
        url: "",
        uploading: true,
      }));
      setUploadedFiles((prev) => [...prev, ...nextFiles]);

      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const uploadEntry = nextFiles[index];
        const sizeMb = file.size / 1024 / 1024;
        if (sizeMb > CHAT_ATTACHMENT_MAX_MB) {
          message.error(
            t(
              "chat.attachment.fileTooLarge",
              `文件 ${file.name} 超过 ${CHAT_ATTACHMENT_MAX_MB}MB 限制`,
            ),
          );
          setUploadedFiles((prev) =>
            prev.filter((item) => item.id !== uploadEntry.id),
          );
          continue;
        }

        try {
          const res = await chatApi.uploadFile(file);
          setUploadedFiles((prev) =>
            prev.map((item) =>
              item.id === uploadEntry.id
                ? { ...item, url: res.url, uploading: false }
                : item,
            ),
          );
        } catch (error) {
          console.error("Upload error:", error);
          message.error(
            t("chat.attachment.uploadFailed", `文件 ${file.name} 上传失败`),
          );
          setUploadedFiles((prev) =>
            prev.filter((item) => item.id !== uploadEntry.id),
          );
        }
      }
    },
    [t],
  );

  const handleAttachClick = useCallback(() => {
    if (sending) return;
    fileInputRef.current?.click();
  }, [sending]);

  const handleFileChange = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      await uploadFiles(Array.from(event.target.files || []));
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    [uploadFiles],
  );

  const handleDeleteAttachment = useCallback((fileId: string) => {
    setUploadedFiles((prev) => prev.filter((file) => file.id !== fileId));
  }, []);

  const handleDragEnter = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (sending || !hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current += 1;
      setIsDraggingFiles(true);
    },
    [sending],
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (sending || !hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      setIsDraggingFiles(true);
    },
    [sending],
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
      if (sending) return;
      void uploadFiles(Array.from(event.dataTransfer.files || []));
    },
    [sending, uploadFiles],
  );

  const handleSend = useCallback(async () => {
    const text = inputValue.trim();
    const completedFiles = uploadedFiles.filter(
      (file) => !file.uploading && file.url,
    );
    const hasUploadingFiles = uploadedFiles.some((file) => file.uploading);
    if (
      sending ||
      (!text && completedFiles.length === 0 && !hasUploadingFiles)
    ) {
      return;
    }
    if (hasUploadingFiles) {
      message.warning(
        t("chat.attachment.stillUploading", "附件还在上传中，请稍候"),
      );
      return;
    }

    // Resolve the real agent ID: craft/plan/ask are UI modes, not real agents
    const MODE_IDS = new Set(["craft", "plan", "ask"]);
    const agentId = MODE_IDS.has(selectedAgent) ? "default" : selectedAgent;

    // Set up the intent object with the exact text we want to send
    let messageText = text;
    if (completedFiles.length > 0) {
      const attachmentsMarkdown = completedFiles
        .map((file) => `📎 [${file.name}](${file.url})`)
        .join("\n");
      messageText = messageText
        ? `${messageText}\n\n${attachmentsMarkdown}`
        : attachmentsMarkdown;
    }

    if (activeMode === "plan") {
      messageText = `/plan ${messageText}`;
    } else if (activeMode === "ask") {
      messageText = `[Ask Mode: 仅回答问题，不要执行任何文件操作、命令执行或工具调用]\n${messageText}`;
    }

    if (selectedSkill) {
      messageText = `/[${getSkillInvocationName(
        selectedSkill,
      )}]\n\n${messageText}`;
    }

    setSending(true);
    if (selectedSkill) {
      const targetAgentId = resolveSkillInstallAgentId({
        selectedAgent: agentId,
        expertTeam: selectedExpertTeam,
      });
      try {
        await ensureSkillInstalledForAgent(selectedSkill, targetAgentId);
      } catch (error) {
        console.error(
          "Failed to prepare selected skill for target agent",
          error,
        );
        message.error("技能安装失败，请稍后重试");
        setSending(false);
        return;
      }
    }

    try {
      // 1. Create the session on the backend natively first to get a real UUID.
      // This bypasses the chat component's buggy local timestamp creation race condition.
      const newChat = await api.createChat({
        name:
          text ||
          completedFiles[0]?.name ||
          t("workbench.attachmentTaskName", "附件任务"),
        agent_id: agentId,
        meta: {
          mode: "task",
          agent_id: agentId,
          active_mode: activeMode,
          ...(selectedExpertTeam
            ? {
                expert_team_id: selectedExpertTeam.id,
                expert_team_name: selectedExpertTeam.name,
              }
            : {}),
        },
        session_id: "",
        user_id: (window as any).currentUserId || "default",
        channel: "console",
      } as any);

      savePendingTaskIntent(newChat.id, {
        prompt: messageText,
        agentId,
        expertTeam: selectedExpertTeam,
      });

      // 2. Navigate directly to the newly created chat UUID, passing the intent
      // so the Task page will automatically submit the prompt upon load.
      navigate(`/task/${newChat.id}`, {
        state: {
          intent: {
            prompt: messageText,
            agentId,
            expertTeam: selectedExpertTeam,
          },
        },
      });
      // Force the Sidebar to fetch the new task immediately instead of waiting for the 15s interval
      window.dispatchEvent(new CustomEvent("refresh-task-list"));
      setInputValue("");
      setUploadedFiles([]);
      setSelectedSkill(null);
    } catch (error) {
      console.error("Failed to create task", error);
      // Fallback: If backend creation fails for some reason, just send the intent
      // to /task and let it try the old flow (though we know it might have race conditions)
      navigate("/task", {
        state: {
          intent: {
            prompt: messageText,
            agentId,
            expertTeam: selectedExpertTeam,
          },
        },
      });
      setInputValue("");
      setUploadedFiles([]);
      setSelectedSkill(null);
    } finally {
      setSending(false);
    }
  }, [
    inputValue,
    navigate,
    sending,
    selectedAgent,
    activeMode,
    selectedExpertTeam,
    selectedSkill,
    uploadedFiles,
    t,
  ]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleTagClick = useCallback(
    (tagKey: string) => {
      setInputValue(buildWorkbenchPrompt(tagKey, t));
      textareaRef.current?.focus();
    },
    [t],
  );

  useLayoutEffect(() => {
    resizeTextareaToContent(textareaRef.current, 220);
  }, [inputValue]);

  return (
    <div className={styles.workbenchPage}>
      {/* Top content wrapper to push input to bottom */}
      <div className={styles.contentWrapper}>
        {/* Mascot & Slogan */}
        <div className={styles.mascotSection}>
          <img
            src="/mascot.png"
            alt="AI Assistant"
            className={styles.mascotAvatar}
          />
          <div className={styles.sloganText}>{t("workbench.slogan")}</div>
          <div className={styles.subtitleText}>
            {t("workbench.subtitle")}
            <span className={styles.statusDot} />
          </div>
        </div>

        {/* Scene Tabs: "开始" label + [代码开发|日常办公] buttons + "任务" label */}
        <div className={styles.sceneTabs}>
          <span className={styles.sceneLabel}>{t("workbench.tabStart")}</span>
          {scenes.map((scene) => (
            <button
              key={scene.key}
              className={`${styles.sceneTab} ${
                activeScene === scene.key ? styles.sceneTabActive : ""
              }`}
              onClick={() => setActiveScene(scene.key)}
            >
              {scene.icon}
              {scene.label}
            </button>
          ))}
          <span className={styles.sceneLabel}>
            {t("workbench.taskLabel", "任务")}
          </span>
        </div>
      </div>

      {/* Quick Action Tags (moved next to input area) */}
      {currentScene.tags.length > 0 && (
        <div className={styles.quickTags}>
          {currentScene.tags.map((tag) => (
            <button
              key={tag.key}
              className={styles.quickTag}
              onClick={() => handleTagClick(tag.key)}
              title={buildWorkbenchPrompt(tag.key, t)}
            >
              <span className={styles.tagIcon}>{tag.icon}</span>
              {tag.label}
            </button>
          ))}
        </div>
      )}

      {/* Input Area (now pushed to bottom) */}
      <div
        className={`${styles.inputArea} ${
          isDraggingFiles ? styles.inputAreaDragging : ""
        }`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {isDraggingFiles && !sending && (
          <div className={styles.dropOverlay} role="status" aria-live="polite">
            <Paperclip size={18} />
            <span>{t("workbench.input.dropFiles", "松开即可上传附件")}</span>
          </div>
        )}
        <div className={styles.inputToolbar}>
          <button className={styles.toolbarBtn} title="@">
            <AtSign size={16} />
          </button>
          <button
            className={styles.toolbarBtn}
            title={t("workbench.input.attachFile", "添加附件")}
            onClick={handleAttachClick}
            disabled={sending}
          >
            <Paperclip size={16} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className={styles.hiddenFileInput}
            onChange={handleFileChange}
          />
        </div>

        {uploadedFiles.length > 0 && (
          <div className={styles.attachmentsArea}>
            {uploadedFiles.map((file) => (
              <div key={file.id} className={styles.attachmentCard}>
                {file.uploading ? (
                  <LoadingOutlined style={{ fontSize: 14, color: "#2563eb" }} />
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
          </div>
        )}

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
          ref={textareaRef}
          className={styles.inputField}
          placeholder={t("workbench.inputPlaceholder")}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={speechState !== "idle"}
          rows={2}
        />

        <div className={styles.inputFooter}>
          <div
            className={styles.footerLeftWrapper}
            style={{ marginLeft: -12, marginTop: -4 }}
          >
            {/* Render ChatToolbar inline */}
            <ChatToolbar />
          </div>

          <div className={styles.footerRight}>
            {speechState !== "idle" && (
              <span className={styles.speechStatus}>
                {speechState === "recording"
                  ? t("workbench.speechListening", "正在听写…")
                  : t("workbench.speechConnecting", "正在连接…")}
              </span>
            )}
            <button
              className={`${styles.footerAction} ${
                speechState === "recording" ? styles.footerActionRecording : ""
              }`}
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
              disabled={speechState === "processing"}
              onClick={handleSpeechToggle}
            >
              {speechState === "recording" ? (
                <Square size={12} fill="currentColor" />
              ) : (
                <Mic size={14} />
              )}
            </button>
            <button
              className={styles.sendBtn}
              disabled={
                (!inputValue.trim() && uploadedFiles.length === 0) ||
                sending ||
                speechState !== "idle"
              }
              onClick={handleSend}
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>

      <div className={styles.aiDisclaimer}>
        内容由 AI 生成，请核实重要信息。
      </div>
    </div>
  );
}
