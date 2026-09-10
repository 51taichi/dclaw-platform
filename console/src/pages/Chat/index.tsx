import { ExpertIdentityContext } from "../../contexts/ExpertIdentityContext";
import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { TaskArtifactCard } from "./components/TaskArtifactCard";
import { Button, Modal, Result, Tooltip } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi, { DRAFT_SESSION_ID, isDraftSessionId } from "./sessionApi";
import {
  appendLiveResponseText,
  resetLiveResponseText,
} from "./sessionApi/liveResponseStore";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { expertTeamsApi } from "../../api/modules/expertTeams";
import { useExpertIdentity } from "../../hooks/useExpertIdentity";
import { agentApi } from "../../api/modules/agent";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
import ModelSelector from "./ModelSelector";
import { useTheme } from "../../contexts/ThemeContext";
import { useRuntimeEvents } from "../../contexts/RuntimeEventContext";
import { useAgentStore } from "../../stores/agentStore";
import type { ExpertTeamTemplate } from "../../api/types/expertTeams";
import {
  loadExpertTeamSelectionForChat,
  saveExpertTeamSelectionForChat,
} from "../../utils/expertTeamSelection";
import { useChatAnywhereInput } from "@agentscope-ai/chat";
import styles from "./index.module.less";
import WorkbenchInput from "../../components/WorkbenchInput";
import { IconButton } from "@agentscope-ai/design";
import ChatActionGroup from "./components/ChatActionGroup";
import ChatHeaderTitle from "./components/ChatHeaderTitle";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { planApi } from "../../api/modules/plan";
import {
  importSkillFromContent,
  parseSkillMetadataFromContent,
} from "./utils/skillImport";
import { scheduleArtifactCardScans } from "./utils/artifactCardScanScheduler";
import RunningSessionNotice from "./components/RunningSessionNotice";
import RuntimeProgressCard from "./components/RuntimeProgressCard";
import { getRouteChatId } from "./routeSession";
import { buildAigcTaskRoute } from "./routeSession";
import {
  projectSuperExpertAigcCards,
  SuperExpertAigcTaskCard,
} from "./components/SuperExpertAigcTaskCard";
import { superExpertPlatformApi } from "../../api/modules/superExpertPlatform";

interface ApprovalMessageData {
  requestId: string;
  sessionId: string;
  rootSessionId?: string;
  agentId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
}

import WhisperSpeechButton, {
  WhisperSpeechButtonRef,
} from "./components/WhisperSpeechButton";
import ArtifactPanel from "./components/ArtifactPanel";
import ExpertTeamStatusStrip from "./components/ExpertTeamStatusStrip";
import BillingFailureAlert from "../../features/billing/BillingFailureAlert";
import { parseInsufficientCreditsFailure } from "../../features/billing/billingFailure";
import type { InsufficientCreditsFailure } from "../../api/types/billing";

import {
  toDisplayUrl,
  copyText,
  extractCopyableText,
  buildModelError,
  normalizeContentUrls,
  rewritePayloadMediaUrls,
  extractUserMessageText,
  extractTextFromMessage,
  setTextareaValue,
  filterApprovalsForSession,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
} from "./utils";

const CHAT_ATTACHMENT_MAX_MB = 10;

interface SessionInfo {
  session_id?: string;
  user_id?: string;
  channel?: string;
}

function buildInitialChatName(text: string): string {
  return text ? text.slice(0, 10) : "Media Message";
}

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

interface CommandSuggestion {
  command: string;
  value: string;
  description: string;
}

function messageRequestsHistoryClear(message: unknown): boolean {
  if (!message || typeof message !== "object") return false;
  const metadata = (message as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object") return false;

  const meta = metadata as Record<string, unknown>;
  if (meta.clear_history === true) return true;

  const nested = meta.metadata;
  return (
    !!nested &&
    typeof nested === "object" &&
    (nested as Record<string, unknown>).clear_history === true
  );
}

function payloadRequestsHistoryClear(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;

  const record = payload as Record<string, unknown>;
  const candidates: unknown[] = [];

  if (record.object === "message") {
    candidates.push(record);
  }

  if (record.object === "response" && Array.isArray(record.output)) {
    candidates.push(...record.output);
  }

  return candidates.some(messageRequestsHistoryClear);
}

function payloadCompletesResponse(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;

  const record = payload as Record<string, unknown>;
  return record.object === "response" && record.status === "completed";
}

function renderSuggestionLabel(command: string, description: string) {
  return (
    <div className={styles.suggestionLabel}>
      <span className={styles.suggestionCommand}>{command}</span>
      <span className={styles.suggestionDescription}>{description}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";

// ---------------------------------------------------------------------------
// Custom hooks
// ---------------------------------------------------------------------------

/** Handle IME composition events to prevent premature Enter key submission. */
function useIMEComposition(isChatActive: () => boolean) {
  const isComposingRef = useRef(false);

  useEffect(() => {
    const handleCompositionStart = () => {
      if (!isChatActive()) return;
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      if (!isChatActive()) return;
      // Small delay for Safari on macOS, which fires keydown after
      // compositionend within the same event loop tick.  Keep this as
      // short as possible so fast typists who hit Space+Enter in quick
      // succession are not blocked.
      setTimeout(() => {
        isComposingRef.current = false;
      }, 50);
    };

    const suppressImeEnter = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      const target = e.target as HTMLElement;
      if (target?.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
        // e.isComposing is the standard flag; isComposingRef covers the
        // post-compositionend grace period needed by Safari.
        if (isComposingRef.current || (e as any).isComposing) {
          e.stopPropagation();
          e.stopImmediatePropagation();
          e.preventDefault();
          return false;
        }
      }
    };

    document.addEventListener("compositionstart", handleCompositionStart, true);
    document.addEventListener("compositionend", handleCompositionEnd, true);
    // Listen on both keydown (Safari) and keypress (legacy) in capture phase.
    document.addEventListener("keydown", suppressImeEnter, true);
    document.addEventListener("keypress", suppressImeEnter, true);

    return () => {
      document.removeEventListener(
        "compositionstart",
        handleCompositionStart,
        true,
      );
      document.removeEventListener(
        "compositionend",
        handleCompositionEnd,
        true,
      );
      document.removeEventListener("keydown", suppressImeEnter, true);
      document.removeEventListener("keypress", suppressImeEnter, true);
    };
  }, [isChatActive]);

  return isComposingRef;
}

/** Fetch and track multimodal capabilities for the active model. */
function useMultimodalCapabilities(
  locationPathname: string,
  isChatActive: () => boolean,
  selectedAgent: string,
) {
  const [multimodalCaps, setMultimodalCaps] = useState<{
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  }>({ supportsMultimodal: false, supportsImage: false, supportsVideo: false });

  const updateCapsIfChanged = useCallback(
    (next: {
      supportsMultimodal: boolean;
      supportsImage: boolean;
      supportsVideo: boolean;
    }) => {
      setMultimodalCaps((prev) =>
        prev.supportsMultimodal === next.supportsMultimodal &&
        prev.supportsImage === next.supportsImage &&
        prev.supportsVideo === next.supportsVideo
          ? prev
          : next,
      );
    },
    [],
  );

  const fetchMultimodalCaps = useCallback(async () => {
    const noCaps = {
      supportsMultimodal: false,
      supportsImage: false,
      supportsVideo: false,
    };
    try {
      const [providers, activeModels] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels({
          scope: "effective",
          agent_id: selectedAgent,
        }),
      ]);
      const activeProviderId = activeModels?.active_llm?.provider_id;
      const activeModelId = activeModels?.active_llm?.model;
      if (!activeProviderId || !activeModelId) {
        updateCapsIfChanged(noCaps);
        return;
      }
      const provider = (providers as ProviderInfo[]).find(
        (p) => p.id === activeProviderId,
      );
      if (!provider) {
        updateCapsIfChanged(noCaps);
        return;
      }
      const allModels: ModelInfo[] = [
        ...(provider.models ?? []),
        ...(provider.extra_models ?? []),
      ];
      const model = allModels.find((m) => m.id === activeModelId);
      updateCapsIfChanged({
        supportsMultimodal: model?.supports_multimodal ?? false,
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      updateCapsIfChanged(noCaps);
    }
  }, [selectedAgent, updateCapsIfChanged]);

  // Fetch caps on mount and whenever refreshKey changes
  useEffect(() => {
    fetchMultimodalCaps();
  }, [fetchMultimodalCaps]);

  // Also poll caps when navigating back to chat
  useEffect(() => {
    if (isChatActive()) {
      fetchMultimodalCaps();
    }
  }, [locationPathname, fetchMultimodalCaps, isChatActive]);

  // Listen for model-switched event from ModelSelector
  useEffect(() => {
    const handler = () => {
      fetchMultimodalCaps();
    };
    window.addEventListener("model-switched", handler);
    return () => window.removeEventListener("model-switched", handler);
  }, [fetchMultimodalCaps]);

  return multimodalCaps;
}

function useMessageHistoryNavigation(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  isChatActive: () => boolean,
  isComposingRef: React.RefObject<boolean>,
) {
  const historyIndexRef = useRef<number>(-1);
  const draftRef = useRef<string>("");

  /** Cached user messages to avoid re-computing on every keydown */
  const userMessagesCacheRef = useRef<string[]>([]);
  const cachedMessageCountRef = useRef<number>(0);

  const getUserMessagesWithText = useCallback((): string[] => {
    if (!chatRef.current?.messages?.getMessages) return [];

    const allMessages = chatRef.current.messages.getMessages();
    if (!Array.isArray(allMessages)) return [];

    const currentCount = allMessages.length;
    if (
      userMessagesCacheRef.current.length > 0 &&
      cachedMessageCountRef.current === currentCount
    ) {
      return userMessagesCacheRef.current;
    }

    const userMessages = allMessages
      .filter((msg) => msg.role === "user")
      .map((msg) => extractTextFromMessage(msg))
      .filter((text) => text.trim().length > 0);

    userMessagesCacheRef.current = userMessages;
    cachedMessageCountRef.current = currentCount;

    return userMessages;
  }, [chatRef]);

  interface MessageResult {
    index: number;
    text: string;
  }

  const findMessageInDirection = (
    messages: string[],
    startIndex: number,
    direction: 1 | -1,
  ): MessageResult | null => {
    const MAX_LOOKUP = 100;
    let lookupIndex = startIndex;
    let steps = 0;

    while (
      lookupIndex >= 0 &&
      lookupIndex < messages.length &&
      steps < MAX_LOOKUP
    ) {
      const messageText = messages[messages.length - 1 - lookupIndex];
      if (messageText) {
        return { index: lookupIndex, text: messageText };
      }
      lookupIndex += direction;
      steps += 1;
    }

    return null;
  };

  const isSuggestionPopupOpen = (textarea: HTMLTextAreaElement): boolean =>
    textarea.value.startsWith("/");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;

      const target = e.target as HTMLElement;
      const isChatSender =
        target?.tagName === "TEXTAREA" &&
        target?.closest('[class*="sender"]') !== null;

      if (!isChatSender) return;
      if (isComposingRef.current || (e as any).isComposing) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const textarea = target as HTMLTextAreaElement;
      const hasSelection = textarea.selectionStart !== textarea.selectionEnd;
      if (hasSelection) return;

      const userMessages = getUserMessagesWithText();

      if (e.key === "ArrowUp") {
        if (isSuggestionPopupOpen(textarea)) return;

        const cursorPosition = textarea.selectionStart || 0;
        const textBeforeCursor = textarea.value.substring(0, cursorPosition);
        const lineBreaks = textBeforeCursor.split("\n").length - 1;
        if (lineBreaks > 0) return;

        if (userMessages.length === 0) return;

        if (historyIndexRef.current === -1) {
          draftRef.current = textarea.value;
        }

        const startIndex = historyIndexRef.current + 1;
        const messageText = findMessageInDirection(userMessages, startIndex, 1);

        if (messageText) {
          e.preventDefault();
          historyIndexRef.current = messageText.index;
          setTextareaValue(textarea, messageText.text);
        }
      } else if (e.key === "ArrowDown") {
        if (historyIndexRef.current < 0) return;

        const cursorPosition = textarea.selectionStart || 0;
        const textAfterCursor = textarea.value.substring(cursorPosition);
        if (textAfterCursor.includes("\n")) return;

        const startIndex = historyIndexRef.current - 1;
        const messageText = findMessageInDirection(
          userMessages,
          startIndex,
          -1,
        );

        if (messageText) {
          e.preventDefault();
          historyIndexRef.current = messageText.index;
          setTextareaValue(textarea, messageText.text);
        } else {
          e.preventDefault();
          historyIndexRef.current = -1;
          setTextareaValue(textarea, draftRef.current);
        }
      }
    };

    const handleFocus = (e: FocusEvent) => {
      const target = e.target as HTMLElement;
      const isChatSender =
        target?.tagName === "TEXTAREA" &&
        target?.closest('[class*="sender"]') !== null;

      if (isChatSender) {
        historyIndexRef.current = -1;
        draftRef.current = "";
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("focusin", handleFocus, true);

    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("focusin", handleFocus, true);
    };
  }, [isChatActive, isComposingRef, getUserMessagesWithText]);
}

function RuntimeLoadingBridge({
  bridgeRef,
}: {
  bridgeRef: { current: RuntimeLoadingBridgeApi | null };
}) {
  const { setLoading, getLoading } = useChatAnywhereInput(
    (value) =>
      ({
        setLoading: value.setLoading,
        getLoading: value.getLoading,
      }) as RuntimeLoadingBridgeApi,
  );

  useEffect(() => {
    if (!setLoading || !getLoading) {
      bridgeRef.current = null;
      return;
    }

    bridgeRef.current = {
      setLoading,
      getLoading,
    };

    return () => {
      if (bridgeRef.current?.setLoading === setLoading) {
        bridgeRef.current = null;
      }
    };
  }, [getLoading, setLoading, bridgeRef]);

  return null;
}

export default function ChatPage({ isClawMode }: { isClawMode?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const chatId = useMemo(
    () => getRouteChatId(location.pathname),
    [location.pathname],
  );
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const {
    selectedAgent,
    selectedExpertTeam,
    currentExpertTeamRun,
    setSelectedExpertTeam,
    setCurrentExpertTeamRun,
  } = useAgentStore();
  const [taskMetadata, setTaskMetadata] = useState<{
    chatId: string;
    agentId?: string;
    mode?: string;
  } | null>(null);
  const taskAgent =
    taskMetadata && taskMetadata.chatId === chatId
      ? taskMetadata.agentId
      : undefined;
  const taskMode =
    taskMetadata && taskMetadata.chatId === chatId
      ? taskMetadata.mode
      : undefined;
  const identityAgentId = taskAgent || selectedAgent;
  const responseIdentity = useExpertIdentity(
    identityAgentId,
    !!selectedExpertTeam,
  );
  const { toolRenderConfig } = usePlugins();
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();
  const { setActiveSessionId, events: runtimeEvents } = useRuntimeEvents();
  const superExpertCards = useMemo(
    () => projectSuperExpertAigcCards(runtimeEvents),
    [runtimeEvents],
  );
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const [planEnabled, setPlanEnabled] = useState(false);
  const [showArtifactPanel, setShowArtifactPanel] = useState(
    isClawMode === true,
  );

  // Magic import skill states
  const [detectedSkill, setDetectedSkill] = useState<{
    name: string;
    description: string;
    content: string;
  } | null>(null);
  const [showMagicImport, setShowMagicImport] = useState(false);
  const [importStatus, setImportStatus] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [isGenerating, setIsGenerating] = useState(false);
  const [runtimeReloadKey, setRuntimeReloadKey] = useState(0);
  const [billingFailure, setBillingFailure] =
    useState<InsufficientCreditsFailure | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const persistedExpertTeamRef = useRef<string>("");

  useEffect(() => {
    const sessionId = chatId && !isDraftSessionId(chatId) ? chatId : null;
    setActiveSessionId(sessionId);
    return () => setActiveSessionId(null);
  }, [chatId, setActiveSessionId]);

  useEffect(() => {
    if (
      currentExpertTeamRun?.state === "paused_insufficient_balance" &&
      !billingFailure
    ) {
      setBillingFailure({
        code: "INSUFFICIENT_CREDITS",
        available_credits: 0,
        required_credits: currentExpertTeamRun.required_credits ?? 0,
        top_up_path: "/wallet",
      });
    }
  }, [billingFailure, currentExpertTeamRun]);

  useEffect(() => {
    const locState = location.state as {
      selectedExpertTeam?: string | ExpertTeamTemplate | null;
    } | null;
    const routeTeam = locState?.selectedExpertTeam;
    if (!routeTeam) return;

    if (typeof routeTeam === "object") {
      setSelectedExpertTeam(routeTeam);
      return;
    }

    let cancelled = false;
    expertTeamsApi
      .getExpertTeam(routeTeam)
      .then((team) => {
        if (!cancelled) setSelectedExpertTeam(team);
      })
      .catch((error) => {
        console.warn("Failed to restore routed expert team:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [location.state, setSelectedExpertTeam]);

  useEffect(() => {
    let cancelled = false;
    if (chatId) {
      sessionApi
        .getSession(chatId)
        .then((session) => {
          if (cancelled) return;
          const meta = (
            session as {
              meta?: { agent_id?: string; active_mode?: string };
            } | null
          )?.meta;
          setTaskMetadata({
            chatId,
            agentId: meta?.agent_id,
            mode: meta?.active_mode,
          });
        })
        .catch(() => {
          if (!cancelled) setTaskMetadata(null);
        });
    } else {
      setTaskMetadata(null);
    }
    return () => {
      cancelled = true;
    };
  }, [chatId]);

  const handleAgentOrModeChange = (agentId?: string, mode?: string) => {
    if (chatId) {
      Modal.confirm({
        title: "切换专家团将开启新对话",
        content: "当前对话正在使用专家团协作，切换到其他专家需要开启新对话。",
        onOk: () => {
          if (agentId !== undefined)
            useAgentStore.getState().setSelectedAgent(agentId);
          if (mode !== undefined)
            useAgentStore.getState().setActiveMode(mode as any);
          navigate(isClawMode ? "/claw" : "/task");
        },
      });
    } else {
      if (agentId !== undefined)
        useAgentStore.getState().setSelectedAgent(agentId);
      if (mode !== undefined)
        useAgentStore.getState().setActiveMode(mode as any);
    }
  };

  const triggerConfetti = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const colors = [
      "#a855f7",
      "#6366f1",
      "#3b82f6",
      "#10b981",
      "#f59e0b",
      "#ef4444",
      "#ec4899",
    ];
    const particles: Array<{
      x: number;
      y: number;
      size: number;
      color: string;
      speedX: number;
      speedY: number;
      rotation: number;
      rotationSpeed: number;
      opacity: number;
    }> = [];

    const startX = window.innerWidth / 2;
    const startY = window.innerHeight * 0.8;

    for (let i = 0; i < 120; i++) {
      particles.push({
        x: startX,
        y: startY,
        size: Math.random() * 8 + 6,
        color: colors[Math.floor(Math.random() * colors.length)],
        speedX: (Math.random() - 0.5) * 15,
        speedY: -Math.random() * 15 - 10,
        rotation: Math.random() * 360,
        rotationSpeed: (Math.random() - 0.5) * 10,
        opacity: 1,
      });
    }

    const renderConfetti = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      let alive = false;

      particles.forEach((p) => {
        if (p.opacity <= 0) return;

        p.x += p.speedX;
        p.y += p.speedY;
        p.speedY += 0.4;
        p.speedX *= 0.98;
        p.rotation += p.rotationSpeed;
        p.opacity -= 0.01;

        if (p.opacity > 0 && p.y < canvas.height) {
          alive = true;
          ctx.save();
          ctx.translate(p.x, p.y);
          ctx.rotate((p.rotation * Math.PI) / 180);
          ctx.fillStyle = p.color;
          ctx.globalAlpha = p.opacity;
          ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size);
          ctx.restore();
        }
      });

      if (alive) {
        requestAnimationFrame(renderConfetti);
      } else {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    };

    renderConfetti();
  };

  const parseSkillMetadata = (text: string) => {
    const parsed = parseSkillMetadataFromContent(text);
    if (parsed) {
      setDetectedSkill(parsed);
      setShowMagicImport(true);
    }
  };

  const monitorStreamText = async (
    response: Response,
    startedChatId?: string,
  ) => {
    if (!response.body) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let accumulatedText = "";
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");

        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i].trim();
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            try {
              const parsed = JSON.parse(dataStr);
              const parsedBillingFailure =
                parseInsufficientCreditsFailure(parsed);
              if (parsedBillingFailure) {
                setBillingFailure(parsedBillingFailure);
              } else if (parsed.object === "message" && parsed.content) {
                accumulatedText += parsed.content;
                appendLiveResponseText(startedChatId, parsed.content);
              } else if (
                parsed.object === "response" &&
                Array.isArray(parsed.output)
              ) {
                for (const item of parsed.output) {
                  if (item.content) {
                    accumulatedText += item.content;
                    appendLiveResponseText(startedChatId, item.content);
                  }
                }
              }
            } catch {
              // Ignore JSON parse errors for stream metadata
            }
          }
        }
        buffer = lines[lines.length - 1];

        if (accumulatedText) {
          parseSkillMetadata(accumulatedText);
        }
      }
    } catch (err) {
      console.error("Monitor stream error:", err);
    } finally {
      reader.releaseLock();
      if (!startedChatId || chatIdRef.current === startedChatId) {
        setIsGenerating(false);
      }
      window.dispatchEvent(new Event("refresh-task-list"));
    }
  };

  const handleMagicImport = async () => {
    if (!detectedSkill) return;
    setImportStatus("loading");
    try {
      const result = await importSkillFromContent(detectedSkill.content, {
        targetAgentId: selectedAgent,
      });

      setImportStatus("success");
      triggerConfetti();

      const inputEl = document.querySelector(".qwenpaw-chat-toolbar");
      if (inputEl) {
        inputEl.classList.add(styles.bounceAnimation);
        setTimeout(() => {
          inputEl.classList.remove(styles.bounceAnimation);
        }, 800);
      }

      setTimeout(() => {
        setShowMagicImport(false);
      }, 3000);

      message.success(
        `✨ 技能「${result.name}」已成功导入到“我的技能”并启用！`,
      );
    } catch (err: any) {
      console.error(err);
      setImportStatus("error");
      message.error(`物理导入失败: ${err.message || err}`);
    }
  };

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig()
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  useEffect(() => {
    if (isClawMode || !chatId || isDraftSessionId(chatId)) return;
    let cancelled = false;

    const restoreExpertTeam = async () => {
      try {
        const chats = await chatApi.listChats({
          user_id: window.currentUserId || DEFAULT_USER_ID,
          channel: window.currentChannel || DEFAULT_CHANNEL,
        });
        if (cancelled) return;
        const chat = chats.find(
          (item) => item.id === chatId || item.session_id === chatId,
        );
        if (!chat) return;

        const run = await expertTeamsApi.getRunByChat(chat.id);
        if (cancelled) return;
        if (run) {
          if (run.team) {
            setSelectedExpertTeam(run.team);
          } else if (run.team_id) {
            const team = await expertTeamsApi.getExpertTeam(run.team_id);
            if (!cancelled) setSelectedExpertTeam(team);
          }
          if (!cancelled) setCurrentExpertTeamRun(run);
          return;
        }

        const metaTeamId =
          typeof chat?.meta?.expert_team_id === "string"
            ? chat.meta.expert_team_id
            : undefined;
        const teamId =
          metaTeamId ||
          loadExpertTeamSelectionForChat(chat.id) ||
          loadExpertTeamSelectionForChat(chatId);
        if (!teamId) return;

        const cached = useAgentStore.getState().selectedExpertTeam;
        const team =
          cached?.id === teamId
            ? cached
            : await expertTeamsApi.getExpertTeam(teamId);
        if (!cancelled) setSelectedExpertTeam(team);
      } catch (error) {
        console.warn("Failed to restore expert team from chat:", error);
      }
    };

    void restoreExpertTeam();

    return () => {
      cancelled = true;
    };
  }, [chatId, isClawMode, setCurrentExpertTeamRun, setSelectedExpertTeam]);

  useEffect(() => {
    if (
      isClawMode ||
      !chatId ||
      isDraftSessionId(chatId) ||
      !selectedExpertTeam
    ) {
      return;
    }

    saveExpertTeamSelectionForChat(chatId, selectedExpertTeam.id);

    const persistKey = `${chatId}:${selectedExpertTeam.id}`;
    if (persistedExpertTeamRef.current === persistKey) return;
    persistedExpertTeamRef.current = persistKey;

    let cancelled = false;
    const persistChatMeta = async () => {
      try {
        const chats = await chatApi.listChats({
          user_id: window.currentUserId || DEFAULT_USER_ID,
          channel: window.currentChannel || DEFAULT_CHANNEL,
        });
        if (cancelled) return;
        const chat = chats.find(
          (item) => item.id === chatId || item.session_id === chatId,
        );
        const existingMeta = chat?.meta || {};
        await chatApi.updateChat(chatId, {
          meta: {
            ...existingMeta,
            expert_team_id: selectedExpertTeam.id,
            expert_team_name: selectedExpertTeam.name,
          },
        });
      } catch (error) {
        console.warn("Failed to persist expert team selection:", error);
      }
    };

    void persistChatMeta();
    return () => {
      cancelled = true;
    };
  }, [chatId, isClawMode, selectedExpertTeam]);

  // MutationObserver to render TaskArtifactCard on triggers (WorkBuddy Card Dynamic Mount)
  useEffect(() => {
    const activeChatId = chatId || "claw-global-session";

    const mountCard = (element: HTMLElement) => {
      // React might re-render and remove our manually inserted container sibling.
      // If the container is gone, we must recreate it even if dataset.mounted is true.
      let container = element.previousSibling as HTMLElement;
      const hasContainer =
        container &&
        container.classList?.contains("qwenpaw-artifact-container");

      if (element.dataset.mounted === "true" && hasContainer) {
        // Only skip if it's marked as mounted AND the container is actually still in the DOM
        return;
      }

      try {
        let filesData = "";
        let targetMountElement = element;

        if (
          element.tagName.toLowerCase() === "a" &&
          element
            .getAttribute("href")
            ?.startsWith("http://qwenpaw.local/?data=")
        ) {
          filesData =
            element
              .getAttribute("href")
              ?.replace("http://qwenpaw.local/?data=", "") || "";

          if (!hasContainer) {
            container = document.createElement("div");
            container.className = "qwenpaw-artifact-container";
            element.parentNode?.insertBefore(container, element);
          }

          element.style.display = "none";
          targetMountElement = container;
        } else {
          filesData = element.getAttribute("data-files") || "";
        }

        if (!filesData) return;

        let files: string[] = [];
        try {
          // React-markdown sometimes URL-encodes the href, so decode it first
          const rawFilesData = decodeURIComponent(filesData.trim());
          const decoded = window.atob(rawFilesData);
          files = JSON.parse(decoded) as string[];
        } catch (e: any) {
          try {
            files = JSON.parse(
              decodeURIComponent(filesData.trim()),
            ) as string[];
          } catch (e2: any) {
            // Display error directly on the screen for debugging
            element.style.display = "inline-block";
            element.style.color = "red";
            element.style.fontSize = "12px";
            element.style.background = "#ffebee";
            element.style.padding = "4px";
            element.innerText = `DEBUG ERR: atob failed, JSON failed. filesData: ${filesData.substring(
              0,
              20,
            )}... err1: ${e?.message}`;
            return;
          }
        }

        // If we reached here, parsing succeeded!
        element.dataset.mounted = "true";

        // Wrap in setTimeout to ensure root.render happens outside of React's current render/commit phase.
        // This prevents the flushSync warning and ensures the component actually mounts during rapid streaming updates.
        setTimeout(() => {
          let root = (targetMountElement as any).__reactRoot;
          if (!root) {
            root = createRoot(targetMountElement);
            (targetMountElement as any).__reactRoot = root;
          }
          root.render(<TaskArtifactCard chatId={activeChatId} files={files} />);
        }, 0);
      } catch (err: any) {
        // Display top-level error directly on the screen for debugging
        element.style.display = "inline-block";
        element.style.color = "red";
        element.style.fontSize = "12px";
        element.style.background = "#ffebee";
        element.style.padding = "4px";
        element.innerText = `DEBUG ERR FATAL: ${err?.message}`;
      }
    };

    const scanForArtifactCards = () => {
      document
        .querySelectorAll<HTMLElement>(
          ".qwenpaw-artifact-card-trigger, a[href^='http://qwenpaw.local/?data=']",
        )
        .forEach(mountCard);
    };

    // Scan a few times after render to catch markdown nodes that arrive before
    // the observer attaches, then rely on MutationObserver instead of polling forever.
    const clearScheduledScans = scheduleArtifactCardScans(scanForArtifactCards);

    // Watch for DOM mutations
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "childList") {
          mutation.addedNodes.forEach((node) => {
            if (node instanceof HTMLElement) {
              if (
                node.classList.contains("qwenpaw-artifact-card-trigger") ||
                (node.tagName.toLowerCase() === "a" &&
                  node
                    .getAttribute("href")
                    ?.startsWith("http://qwenpaw.local/?data="))
              ) {
                mountCard(node);
              } else {
                node
                  .querySelectorAll<HTMLElement>(
                    ".qwenpaw-artifact-card-trigger, a[href^='http://qwenpaw.local/?data=']",
                  )
                  .forEach(mountCard);
              }
            }
          });
        } else if (mutation.type === "attributes") {
          const node = mutation.target;
          if (node instanceof HTMLElement) {
            if (
              node.tagName.toLowerCase() === "a" &&
              node
                .getAttribute("href")
                ?.startsWith("http://qwenpaw.local/?data=")
            ) {
              mountCard(node);
            } else if (
              node.classList.contains("qwenpaw-artifact-card-trigger")
            ) {
              mountCard(node);
            }
          }
        } else if (mutation.type === "characterData") {
          const node = mutation.target.parentElement;
          if (node instanceof HTMLElement) {
            if (
              node.tagName.toLowerCase() === "a" &&
              node
                .getAttribute("href")
                ?.startsWith("http://qwenpaw.local/?data=")
            ) {
              mountCard(node);
            }
          }
        }
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["href", "data-files"],
      characterData: true,
    });

    return () => {
      observer.disconnect();
      clearScheduledScans();
    };
  }, [chatId]);

  const isChatActiveRef = useRef(false);
  isChatActiveRef.current = location.pathname.startsWith("/claw");

  const isChatActive = useCallback(() => isChatActiveRef.current, []);

  // Consume approvals from Context and filter by current session.
  // Uses a serialized key to avoid creating a new Map (and triggering
  // re-renders of the entire Chat tree) when the filtered result is identical.
  const prevApprovalKeyRef = useRef("");
  const [approvalRouteSessionId, setApprovalRouteSessionId] = useState<
    string | null
  >(null);

  useEffect(() => {
    let cancelled = false;

    if (!chatId || isDraftSessionId(chatId)) {
      setApprovalRouteSessionId(null);
      return () => {
        cancelled = true;
      };
    }

    sessionApi
      .getSessionIdForChatId(chatId)
      .then((sessionId) => {
        if (!cancelled) setApprovalRouteSessionId(sessionId);
      })
      .catch(() => {
        if (!cancelled) setApprovalRouteSessionId(chatId);
      });

    return () => {
      cancelled = true;
    };
  }, [chatId]);

  useEffect(() => {
    const sessionApprovals = filterApprovalsForSession(approvals, [
      window.currentSessionId,
      chatId,
      approvalRouteSessionId,
    ]);

    // Build a stable key from the filtered request IDs so we can skip
    // the Map rebuild when nothing changed (avoids re-render every 2.5s poll).
    const approvalKey = sessionApprovals
      .map((a) => a.request_id)
      .sort()
      .join(",");

    if (approvalKey === prevApprovalKeyRef.current) return;
    prevApprovalKeyRef.current = approvalKey;

    const newMap = new Map<string, ApprovalMessageData>();
    for (const approval of sessionApprovals) {
      newMap.set(approval.request_id, {
        requestId: approval.request_id,
        sessionId: approval.session_id,
        rootSessionId: approval.root_session_id,
        agentId: approval.agent_id,
        toolName: approval.tool_name,
        severity: approval.severity,
        findingsCount: approval.findings_count,
        findingsSummary: approval.findings_summary,
        toolParams: approval.tool_params,
        createdAt: approval.created_at,
        timeoutSeconds: approval.timeout_seconds,
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, chatId, approvalRouteSessionId]);

  const handleApprove = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      const rootSessionId =
        request.rootSessionId || window.currentSessionId || chatId || "";

      try {
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand(
          "approve",
          requestId,
          rootSessionId,
        );
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.approved"));

        // Delay removal to let exit animation complete
        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300);
      } catch (error) {
        message.error(t("approval.approveFailed"));
        console.error("Failed to approve:", error);
      }
    },
    [approvalRequests, chatId, t, message, setApprovals],
  );

  const handleDeny = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      // Use currentSessionId (root session) instead of request.sessionId (sub-agent session)
      const rootSessionId =
        request.rootSessionId || window.currentSessionId || chatId || "";

      try {
        // Add exit animation class
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand("deny", requestId, rootSessionId);
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.denied"));

        // Delay removal to let animation complete
        // Backend will remove from pending list, next poll will update UI
        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300); // Match animation duration
      } catch (error) {
        message.error(t("approval.denyFailed"));
        console.error("Failed to deny:", error);
      }
    },
    [approvalRequests, chatId, t, message, setApprovals],
  );

  // Use custom hooks for better separation of concerns
  const isComposingRef = useIMEComposition(isChatActive);
  const multimodalCaps = useMultimodalCapabilities(
    location.pathname,
    isChatActive,
    selectedAgent,
  );

  const lastSessionIdRef = useRef<string | null>(null);
  /** Tracks the stale auto-selected session ID that was skipped on init, so we can suppress its late-arriving onSessionSelected callback. */
  const staleAutoSelectedIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  const pendingClearHistoryRef = useRef(false);
  const whisperSpeechRef = useRef<WhisperSpeechButtonRef>(null);
  const [whisperEnabled, setWhisperEnabled] = useState(false);

  // Check if Whisper transcription is configured
  useEffect(() => {
    agentApi
      .getTranscriptionProviderType()
      .then((res: any) => {
        setWhisperEnabled(res.transcription_provider_type !== "disabled");
      })
      .catch(() => setWhisperEnabled(false));
  }, []);

  const handleWhisperTranscription = useCallback((text: string) => {
    const senderContainer = document.querySelector('[class*="sender"]');
    const textarea = senderContainer?.querySelector(
      "textarea",
    ) as HTMLTextAreaElement | null;
    if (textarea) {
      const currentValue = textarea.value || "";
      const newValue = currentValue ? `${currentValue} ${text}` : text;
      setTextareaValue(textarea, newValue);
      textarea.focus();
    }
  }, []);

  useMessageHistoryNavigation(chatRef, isChatActive, isComposingRef);

  // Shortcut key for voice recording (Ctrl+Shift+M or Cmd+Shift+M on Mac)
  useEffect(() => {
    const handleShortcut = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      // Check for Ctrl+Shift+M (Windows/Linux) or Cmd+Shift+M (Mac)
      if (
        (e.ctrlKey || e.metaKey) &&
        e.shiftKey &&
        e.key.toLowerCase() === "m"
      ) {
        e.preventDefault();
        if (whisperEnabled) {
          whisperSpeechRef.current?.toggleRecording();
        }
      }
    };
    document.addEventListener("keydown", handleShortcut);
    return () => document.removeEventListener("keydown", handleShortcut);
  }, [isChatActive, whisperEnabled]);
  chatIdRef.current = chatId;
  navigateRef.current = navigate;

  const scheduleHistoryClear = useCallback(() => {
    queueMicrotask(() => {
      if (!pendingClearHistoryRef.current) return;
      pendingClearHistoryRef.current = false;
      chatRef.current?.messages.removeAllMessages();
    });
  }, []);

  // Tell sessionApi which session to put first in getSessionList, so the library's
  // useMount auto-selects the correct session without an extra getSession round-trip.
  if (chatId && sessionApi.preferredChatId !== chatId) {
    sessionApi.preferredChatId = chatId;
  }

  // Register session API event callbacks for URL synchronization

  useEffect(() => {
    sessionApi.onSessionIdResolved = (tempId, realId) => {
      if (!isChatActiveRef.current) return;
      if (window.currentSessionId !== tempId) {
        return;
      }
      // Update URL when realId is resolved, regardless of current chatId
      // (chatId may be undefined if URL was cleared in onSessionCreated)
      lastSessionIdRef.current = realId;
      navigateRef.current(`/${isClawMode ? "claw" : "task"}/${realId}`, {
        replace: true,
      });
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      // Clear URL when current session is removed
      // Check if removed session matches current session (by realId or sessionId)
      const currentRealId = sessionApi.getRealIdForSession(
        chatIdRef.current || "",
      );
      if (chatIdRef.current === removedId || currentRealId === removedId) {
        lastSessionIdRef.current = null;
        navigateRef.current(`/${isClawMode ? "claw" : "task"}`, {
          replace: true,
        });
      }
    };

    sessionApi.onSessionSelected = (
      sessionId: string | null | undefined,
      realId: string | null,
    ) => {
      if (!isChatActiveRef.current) return;
      // Update URL when session is selected and different from current
      const targetId = realId || sessionId;
      if (!targetId) return;

      // If a preferred chatId from the URL exists and no navigation has happened yet,
      // skip the library's initial auto-selection (always first session).
      // ChatSessionInitializer will apply the correct selection afterward.
      if (
        chatIdRef.current &&
        lastSessionIdRef.current === null &&
        targetId !== chatIdRef.current
      ) {
        lastSessionIdRef.current = targetId;
        // Record the stale ID so its delayed getSession callback is also suppressed.
        staleAutoSelectedIdRef.current = targetId;
        return;
      }

      // Suppress the stale getSession callback that arrives after the correct session loads.
      if (
        staleAutoSelectedIdRef.current &&
        staleAutoSelectedIdRef.current === targetId
      ) {
        staleAutoSelectedIdRef.current = null;
        return;
      }

      if (targetId !== lastSessionIdRef.current) {
        lastSessionIdRef.current = targetId;
        navigateRef.current(`/${isClawMode ? "claw" : "task"}/${targetId}`, {
          replace: true,
        });
      }
    };

    sessionApi.onSessionCreated = () => {
      if (!isChatActiveRef.current) return;
      // Only clear URL if the user is genuinely creating a new session (no chatId in URL).
      // If chatIdRef.current is set, we are in an existing conversation and should NOT
      // navigate away — this prevents the "ghost new task" bug where ensureSession()
      // races with a stale getCurrentSessionId() and spawns an unwanted new session.
      if (!chatIdRef.current) {
        lastSessionIdRef.current = null;
        navigateRef.current(`/${isClawMode ? "claw" : "task"}`, {
          replace: true,
        });
      }
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
      sessionApi.onSessionSelected = null;
      sessionApi.onSessionCreated = null;
      sessionApi.onGeneratingStatusChange = undefined;
    };
  }, []);

  // Sync isGenerating with sessionApi's active status.
  useEffect(() => {
    sessionApi.onGeneratingStatusChange = (generating: boolean) => {
      setIsGenerating(generating);
    };
  }, []);

  useEffect(() => {
    if (!isGenerating || !chatId || isDraftSessionId(chatId)) return;

    let cancelled = false;
    let inFlight = false;
    let controller: AbortController | null = null;

    const checkGenerationStatus = async () => {
      if (cancelled || inFlight || document.visibilityState === "hidden") {
        return;
      }
      const activeChatId = chatIdRef.current || window.currentSessionId;
      if (activeChatId !== chatId) return;

      try {
        inFlight = true;
        controller = new AbortController();
        const status = await chatApi.getChatStatus(
          chatId,
          selectedAgent,
          controller.signal,
        );
        if (cancelled) return;

        if (status.status !== "running") {
          setIsGenerating(false);
          void sessionApi
            .getSession(chatId)
            .catch((error) => {
              console.error("Failed to refresh completed session:", error);
            })
            .finally(() => {
              setRuntimeReloadKey((key) => key + 1);
            });
        }
      } catch (error) {
        if (!cancelled && (error as Error).name !== "AbortError") {
          console.error("Failed to poll chat status:", error);
        }
      } finally {
        inFlight = false;
        controller = null;
      }
    };

    const timer = window.setInterval(checkGenerationStatus, 2000);
    void checkGenerationStatus();

    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, [chatId, isGenerating, selectedAgent]);

  // Setup multimodal capabilities tracking via custom hook

  // Refresh chat when selectedAgent changes, preserving last active chat per agent
  const { setLastChatId, getLastChatId } = useAgentStore();
  const prevSelectedAgentRef = useRef(selectedAgent);
  useEffect(() => {
    const prevAgent = prevSelectedAgentRef.current;
    if (prevAgent !== selectedAgent && prevAgent !== undefined) {
      // Save current chat ID for the agent we're leaving
      const currentChatId =
        chatIdRef.current || lastSessionIdRef.current || undefined;
      if (currentChatId && prevAgent) {
        setLastChatId(prevAgent, currentChatId);
      }

      // DO NOT navigate away. Stay in the current chat so the new expert can continue it!
      // DO NOT increment refreshKey because remounting causes the chat history to disappear / reload issues.
      // The options object uses useMemo with selectedAgent, so the new agent_id will be used automatically.
    }
    prevSelectedAgentRef.current = selectedAgent;
  }, [selectedAgent, setLastChatId, getLastChatId]);

  const copyResponse = useCallback(
    async (response: CopyableResponse) => {
      try {
        await copyText(extractCopyableText(response));
        message.success(t("common.copied"));
      } catch {
        message.error(t("common.copyFailed"));
      }
    },
    [t],
  );

  const customFetch = useCallback(
    async (data: {
      input?: Array<Record<string, unknown>>;
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const requestAgentId =
        selectedExpertTeam?.leader_agent_id || selectedAgent;
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
        "X-Agent-Id": requestAgentId,
      };

      try {
        const activeModels = await providerApi.getActiveModels({
          scope: "effective",
          agent_id: requestAgentId,
        });
        if (
          !activeModels?.active_llm?.provider_id ||
          !activeModels?.active_llm?.model
        ) {
          setShowModelPrompt(true);
          return buildModelError();
        }
      } catch {
        setShowModelPrompt(true);
        return buildModelError();
      }

      const { input = [], biz_params } = data;
      const session: SessionInfo = input[input.length - 1]?.session || {};
      const lastInput = input.slice(-1);
      const lastMsg = lastInput[0];
      const rewrittenInput =
        lastMsg?.content && Array.isArray(lastMsg.content)
          ? [
              {
                ...lastMsg,
                content: lastMsg.content.map(normalizeContentUrls),
              },
            ]
          : lastInput;

      const routeChatId = chatIdRef.current || chatId;
      const routeSessionId = routeChatId
        ? await sessionApi.getSessionIdForChatId(routeChatId)
        : null;
      const isNewRoute = !routeChatId || isDraftSessionId(routeChatId);

      const requestBody = {
        input: rewrittenInput,
        session_id: isNewRoute
          ? DRAFT_SESSION_ID
          : routeSessionId ||
            window.currentSessionId ||
            session?.session_id ||
            "",
        user_id: window.currentUserId || session?.user_id || DEFAULT_USER_ID,
        channel: isClawMode
          ? "claw"
          : window.currentChannel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        ...(selectedExpertTeam
          ? { expert_team_id: selectedExpertTeam.id }
          : {}),
        ...biz_params,
      };

      let submittedSessionId = String(requestBody.session_id || "");
      const userText = rewrittenInput
        .filter((m: any) => m.role === "user")
        .map(extractUserMessageText)
        .join("\n")
        .trim();

      let precreatedChatId: string | null = null;
      if (isDraftSessionId(submittedSessionId)) {
        const createdChat = await chatApi.createChat({
          name: buildInitialChatName(userText),
          session_id: "",
          user_id: requestBody.user_id,
          channel: requestBody.channel,
          meta: {
            ...(isClawMode ? { mode: "claw" } : {}),
            ...(selectedExpertTeam
              ? {
                  expert_team_id: selectedExpertTeam.id,
                  expert_team_name: selectedExpertTeam.name,
                }
              : {}),
          },
        });

        precreatedChatId = createdChat.id;
        if (selectedExpertTeam) {
          saveExpertTeamSelectionForChat(createdChat.id, selectedExpertTeam.id);
        }
        submittedSessionId = createdChat.session_id || createdChat.id;
        requestBody.session_id = submittedSessionId;
        requestBody.user_id = createdChat.user_id || requestBody.user_id;
        requestBody.channel = createdChat.channel || requestBody.channel;
        sessionApi.recordCreatedChat(createdChat);
        lastSessionIdRef.current = createdChat.id;
        navigateRef.current(
          `/${isClawMode ? "claw" : "task"}/${createdChat.id}`,
          { replace: true },
        );
      }

      const backendChatId =
        precreatedChatId ??
        routeChatId ??
        sessionApi.getRealIdForSession(submittedSessionId) ??
        chatIdRef.current ??
        submittedSessionId;
      if (backendChatId) {
        resetLiveResponseText(backendChatId);
        if (userText) {
          sessionApi.setLastUserMessage(backendChatId, userText);
        }
      }

      setDetectedSkill(null);
      setBillingFailure(null);
      setShowMagicImport(false);
      setImportStatus("idle");

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      const resolvedChatId =
        response.headers.get("X-QwenPaw-Chat-Id") || precreatedChatId;
      if (resolvedChatId && selectedExpertTeam) {
        saveExpertTeamSelectionForChat(resolvedChatId, selectedExpertTeam.id);
      }
      const expertTeamRunId = response.headers.get(
        "X-QwenPaw-Expert-Team-Run-Id",
      );
      if (expertTeamRunId) {
        setCurrentExpertTeamRun({
          id: expertTeamRunId,
          team_id: selectedExpertTeam?.id || "",
          root_chat_id: resolvedChatId || precreatedChatId || "",
          root_session_id: submittedSessionId,
          user_id: String(requestBody.user_id || ""),
          state: "running",
          members:
            selectedExpertTeam?.members.map((member) => ({
              id: `${expertTeamRunId}:${member.key}`,
              run_id: expertTeamRunId,
              member_key: member.key,
              agent_id: member.agent_id,
              display_name: member.display_name,
              role: member.role,
              avatar: member.avatar,
              state: "pending",
            })) || [],
          team: selectedExpertTeam || null,
        });
      }
      if (resolvedChatId && submittedSessionId) {
        const wasStillSubmittedSession =
          window.currentSessionId === submittedSessionId;
        sessionApi.resolveSubmittedSession(submittedSessionId, resolvedChatId);
        resetLiveResponseText(resolvedChatId);
        if (userText) {
          sessionApi.setLastUserMessage(resolvedChatId, userText);
        }

        const urlMatchesSubmittedSession =
          !chatIdRef.current || chatIdRef.current === submittedSessionId;

        if (
          resolvedChatId !== chatIdRef.current &&
          wasStillSubmittedSession &&
          urlMatchesSubmittedSession
        ) {
          lastSessionIdRef.current = resolvedChatId;
          navigateRef.current(
            `/${isClawMode ? "claw" : "task"}/${resolvedChatId}`,
            { replace: true },
          );
        }
      }

      const clonedResponse = response.clone();
      setIsGenerating(true);
      window.dispatchEvent(new Event("refresh-task-list"));
      void monitorStreamText(
        clonedResponse,
        resolvedChatId || backendChatId || submittedSessionId || chatId,
      );

      return response;
    },
    [selectedAgent, selectedExpertTeam, setCurrentExpertTeamRun, isClawMode],
  );

  const handleFileUpload = useCallback(
    async (options: {
      file: File;
      onSuccess: (body: { url?: string; thumbUrl?: string }) => void;
      onError?: (e: Error) => void;
      onProgress?: (e: { percent?: number }) => void;
    }) => {
      const { file, onSuccess, onError, onProgress } = options;
      try {
        // Warn when model has no multimodal support
        if (!multimodalCaps.supportsMultimodal) {
          message.warning(t("chat.attachments.multimodalWarning"));
        } else if (
          multimodalCaps.supportsImage &&
          !multimodalCaps.supportsVideo &&
          !file.type.startsWith("image/")
        ) {
          // Warn (not block) when only image is supported
          message.warning(t("chat.attachments.imageOnlyWarning"));
        }
        const sizeMb = file.size / 1024 / 1024;
        const isWithinLimit = sizeMb < CHAT_ATTACHMENT_MAX_MB;

        if (!isWithinLimit) {
          message.error(
            t("chat.attachments.fileSizeExceeded", {
              limit: CHAT_ATTACHMENT_MAX_MB,
              size: sizeMb.toFixed(2),
            }),
          );
          onError?.(new Error(`File size exceeds ${CHAT_ATTACHMENT_MAX_MB}MB`));
          return;
        }

        const res = await chatApi.uploadFile(file);
        onProgress?.({ percent: 100 });
        onSuccess({ url: chatApi.filePreviewUrl(res.url) });
      } catch (e) {
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
    },
    [multimodalCaps, t],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const commandSuggestions: CommandSuggestion[] = [
      {
        command: "/clear",
        value: "clear",
        description: t("chat.commands.clear.description"),
      },
      {
        command: "/compact",
        value: "compact",
        description: t("chat.commands.compact.description"),
      },
      {
        command: "/mission",
        value: "mission",
        description: t("chat.commands.mission.description"),
      },
      {
        command: "/skills",
        value: "skills",
        description: t("chat.commands.skills.description"),
      },
    ];
    if (planEnabled) {
      commandSuggestions.push({
        command: "/plan",
        value: "plan ",
        description: t("chat.commands.plan.description"),
      });
    }

    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) return false;
      return true;
    };

    return {
      ...i18nConfig,
      theme: {
        ...defaultConfig.theme,
        darkMode: isDark,
        leftHeader: {
          ...defaultConfig.theme.leftHeader,
        },
        rightHeader: (
          <>
            <ChatSessionInitializer />
            <RuntimeLoadingBridge bridgeRef={runtimeLoadingBridgeRef} />
            {!isClawMode && <ChatHeaderTitle />}
            <span style={{ flex: 1 }} />
            {!isClawMode && <ModelSelector chatId={chatId} />}
            <ChatActionGroup
              planEnabled={planEnabled}
              isClawMode={isClawMode}
            />
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        nick: responseIdentity.name,
        avatar: responseIdentity.avatar,
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: !whisperEnabled,
        prefix: whisperEnabled ? (
          <WhisperSpeechButton
            ref={whisperSpeechRef}
            onTranscription={handleWhisperTranscription}
          />
        ) : undefined,
        attachments: {
          multiple: true,
          trigger: function (props: any) {
            const tooltipKey = multimodalCaps.supportsMultimodal
              ? multimodalCaps.supportsImage && !multimodalCaps.supportsVideo
                ? "chat.attachments.tooltipImageOnly"
                : "chat.attachments.tooltip"
              : "chat.attachments.tooltipNoMultimodal";
            return (
              <Tooltip title={t(tooltipKey, { limit: CHAT_ATTACHMENT_MAX_MB })}>
                <IconButton
                  disabled={props?.disabled}
                  icon={<SparkAttachmentLine />}
                  bordered={false}
                />
              </Tooltip>
            );
          },
          customRequest: handleFileUpload,
        },
        placeholder: t("chat.inputPlaceholder"),
        suggestions: commandSuggestions.map((item) => ({
          label: renderSuggestionLabel(item.command, item.description),
          value: item.value,
        })),
      },
      session: {
        multiple: true,
        hideBuiltInSessionList: true,
        api: sessionApi,
      },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        responseParser: (chunk: string) => {
          const payload = JSON.parse(chunk) as Record<string, unknown>;

          if (payloadRequestsHistoryClear(payload)) {
            pendingClearHistoryRef.current = true;
            if (payloadCompletesResponse(payload)) {
              scheduleHistoryClear();
            }
          }
          const currentId = window.currentSessionId || chatId || "";
          return rewritePayloadMediaUrls(
            payload,
            currentId,
            selectedAgent,
          ) as any;
        },
        replaceMediaURL: (url: string) => {
          const currentId = window.currentSessionId || chatId || "";
          return toDisplayUrl(url, currentId, selectedAgent);
        },
        cancel(data: { session_id: string }) {
          const resolvedChatId =
            sessionApi.getRealIdForSession(data.session_id) ?? data.session_id;
          if (resolvedChatId) {
            chatApi.stopChat(resolvedChatId).catch((err) => {
              console.error("Failed to stop chat:", err);
            });
          }
        },
        async reconnect(data: { session_id: string; signal?: AbortSignal }) {
          const headers: Record<string, string> = {
            "Content-Type": "application/json",
            ...buildAuthHeaders(),
          };

          return fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: window.currentSessionId || data.session_id,
              user_id: window.currentUserId || DEFAULT_USER_ID,
              channel: window.currentChannel || DEFAULT_CHANNEL,
            }),
            signal: data.signal,
          });
        },
      },
      customToolRenderConfig:
        Object.keys(toolRenderConfig).length > 0 ? toolRenderConfig : undefined,
      cards: {
        AgentScopeRuntimeResponseCard: (cardProps: any) => (
          <RuntimeProgressCard
            {...cardProps}
            chatId={window.currentSessionId || chatId || ""}
            agentId={selectedAgent}
            identity={responseIdentity}
          />
        ),
      },
      actions: {
        list: [
          {
            icon: (
              <span title={t("common.copy")}>
                <SparkCopyLine />
              </span>
            ),
            onClick: ({ data }: { data: CopyableResponse }) => {
              void copyResponse(data);
            },
          },
        ],
        replace: true,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [
    customFetch,
    copyResponse,
    handleFileUpload,
    t,
    isDark,
    multimodalCaps,
    toolRenderConfig,
    scheduleHistoryClear,
    planEnabled,
    chatId,
    selectedAgent,
    responseIdentity,
  ]);

  return (
    <ExpertIdentityContext.Provider value={responseIdentity}>
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "row",
          position: "relative",
        }}
      >
        {/* Main chat area */}
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            position: "relative",
          }}
        >
          <canvas ref={canvasRef} className={styles.confettiCanvas} />

          <div className={styles.chatMessagesArea}>
            <AgentScopeRuntimeWebUI
              key={`${selectedAgent}:${runtimeReloadKey}`}
              ref={chatRef}
              options={options}
            />
            {superExpertCards.length > 0 ? (
              <div className={styles.superExpertCards}>
                {superExpertCards.map((projection) => (
                  <SuperExpertAigcTaskCard
                    key={projection.materialTaskId}
                    projection={projection}
                    onCommand={async (_, materialTaskId) => {
                      if (!projection.installationId || !projection.binding) {
                        throw new Error("AIGC task binding is unavailable");
                      }
                      if (projection.status !== "IN_PROGRESS") {
                        const eventId = crypto.randomUUID();
                        await superExpertPlatformApi.command(
                          "aigc.task.resume",
                          {
                            installation_id: projection.installationId,
                            contract_version: "1",
                            idempotency_key: eventId,
                            arguments: {
                              event_id: eventId,
                              binding: projection.binding,
                            },
                          },
                        );
                      }
                      navigate(buildAigcTaskRoute(materialTaskId));
                    }}
                  />
                ))}
              </div>
            ) : null}
            {billingFailure && (
              <BillingFailureAlert
                failure={billingFailure}
                pausedRunId={
                  currentExpertTeamRun?.state === "paused_insufficient_balance"
                    ? currentExpertTeamRun.id
                    : null
                }
                onContinue={async (runId) => {
                  const resumed = await expertTeamsApi.continueRun(runId);
                  setCurrentExpertTeamRun(resumed);
                  setBillingFailure(null);
                }}
              />
            )}
            <WorkbenchInput
              isClawMode={isClawMode}
              isGenerating={isGenerating}
              topAccessory={
                (isGenerating && !!chatId && !isDraftSessionId(chatId)) ||
                (!isClawMode &&
                  (selectedExpertTeam || currentExpertTeamRun)) ? (
                  <>
                    <RunningSessionNotice
                      visible={
                        isGenerating && !!chatId && !isDraftSessionId(chatId)
                      }
                      variant="inline"
                    />
                    {!isClawMode &&
                      (selectedExpertTeam || currentExpertTeamRun) && (
                        <ExpertTeamStatusStrip
                          chatId={chatId}
                          visible
                          variant="composer"
                        />
                      )}
                  </>
                ) : null
              }
              onStop={() => {
                const currentSession = window.currentSessionId || chatId || "";
                const resolvedChatId =
                  sessionApi.getRealIdForSession(currentSession) ??
                  currentSession;
                if (resolvedChatId) {
                  chatApi.stopChat(resolvedChatId).catch(console.error);
                  setIsGenerating(false);
                }
              }}
              onSubmit={(text) => {
                (chatRef.current?.input.submit as any)({ query: text });
              }}
              overrideSelectedAgent={taskAgent}
              overrideActiveMode={taskMode}
              onAgentChange={(agent) =>
                handleAgentOrModeChange(agent, undefined)
              }
              onModeChange={(mode) => handleAgentOrModeChange(undefined, mode)}
            />
          </div>

          {showMagicImport && detectedSkill && (
            <div className={styles.magicImportCard}>
              <div className={styles.magicImportLeft}>
                {importStatus === "success" ? (
                  <span className={styles.magicImportSuccessIcon}>🎉</span>
                ) : importStatus === "loading" ? (
                  <span
                    className="animate-spin"
                    style={{ display: "inline-block" }}
                  >
                    🔮
                  </span>
                ) : (
                  <span>✨</span>
                )}
              </div>
              <div className={styles.magicImportContent}>
                <div className={styles.magicImportTitle}>
                  <span>【AI 技能创作就绪】</span>
                  {detectedSkill.name}
                </div>
                <div className={styles.magicImportDesc}>
                  {detectedSkill.description}
                </div>
              </div>
              <div className={styles.magicImportAction}>
                <Button
                  className={styles.magicImportBtn}
                  onClick={handleMagicImport}
                  loading={importStatus === "loading"}
                  disabled={importStatus === "success"}
                >
                  {importStatus === "success"
                    ? "已成功导入"
                    : importStatus === "loading"
                    ? "导入中..."
                    : "导入并启用到我的技能"}
                </Button>
              </div>
            </div>
          )}

          {/* Render approval cards as overlays */}
          {Array.from(approvalRequests.values()).map((request) => (
            <div
              key={request.requestId}
              data-approval-id={request.requestId}
              style={{
                position: "fixed",
                bottom: 80,
                right: 24,
                zIndex: 1000,
                maxWidth: 480,
                width: "calc(100vw - 48px)",
              }}
            >
              <ApprovalCard
                requestId={request.requestId}
                agentId={request.agentId}
                toolName={request.toolName}
                severity={request.severity}
                findingsCount={request.findingsCount}
                findingsSummary={request.findingsSummary}
                toolParams={request.toolParams}
                createdAt={request.createdAt}
                timeoutSeconds={request.timeoutSeconds}
                sessionId={request.sessionId}
                rootSessionId={request.rootSessionId}
                onApprove={handleApprove}
                onDeny={handleDeny}
                onCancel={() => {
                  const sessionId =
                    request.rootSessionId || window.currentSessionId || "";
                  const resolvedChatId =
                    sessionApi.getRealIdForSession(sessionId) ??
                    chatIdRef.current ??
                    sessionId;

                  if (resolvedChatId) {
                    console.log(
                      "[Chat] Calling stopChat with:",
                      resolvedChatId,
                    );
                    chatApi
                      .stopChat(resolvedChatId)
                      .then(() => {
                        console.log("[Chat] stopChat succeeded");
                        setApprovals((prev) =>
                          prev.filter(
                            (item) =>
                              item.root_session_id !== request.rootSessionId,
                          ),
                        );
                      })
                      .catch((err) => {
                        console.error("[Chat] stopChat failed:", err);
                      });
                  } else {
                    console.warn(
                      "[Chat] No chat_id resolved, cannot cancel task",
                    );
                  }
                }}
              />
            </div>
          ))}

          <Modal
            open={showModelPrompt}
            closable={false}
            footer={null}
            width={480}
            styles={{
              content: isDark
                ? {
                    background: "#1f1f1f",
                    boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                  }
                : undefined,
            }}
          >
            <Result
              icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
              title={
                <span
                  style={{
                    color: isDark ? "rgba(255,255,255,0.88)" : undefined,
                  }}
                >
                  {t("modelConfig.promptTitle")}
                </span>
              }
              subTitle={
                <span
                  style={{
                    color: isDark ? "rgba(255,255,255,0.55)" : undefined,
                  }}
                >
                  {t("modelConfig.promptMessage")}
                </span>
              }
              extra={[
                <Button key="skip" onClick={() => setShowModelPrompt(false)}>
                  {t("modelConfig.skipButton")}
                </Button>,
                <Button
                  key="configure"
                  type="primary"
                  icon={<SettingOutlined />}
                  onClick={() => {
                    setShowModelPrompt(false);
                    navigate("/models");
                  }}
                >
                  {t("modelConfig.configureButton")}
                </Button>,
              ]}
            />
          </Modal>
        </div>

        {/* Right-side artifact panel */}
        {!isClawMode && (
          <ArtifactPanel
            visible={showArtifactPanel}
            onToggle={() => setShowArtifactPanel(!showArtifactPanel)}
            isClawMode={isClawMode}
            chatId={chatId}
          />
        )}
      </div>
    </ExpertIdentityContext.Provider>
  );
}
