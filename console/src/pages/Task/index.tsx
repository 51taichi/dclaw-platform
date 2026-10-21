import { ExpertIdentityContext } from "../../contexts/ExpertIdentityContext";
import { useExpertIdentity } from "../../hooks/useExpertIdentity";
import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
  useChatAnywhereSessionsState,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, Tooltip } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi, {
  DRAFT_SESSION_ID,
  isDraftSessionId,
} from "../Chat/sessionApi";
import {
  appendLiveResponseText,
  resetLiveResponseText,
} from "../Chat/sessionApi/liveResponseStore";
import defaultConfig, {
  getDefaultConfig,
} from "../Chat/OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { expertTeamsApi } from "../../api/modules/expertTeams";
import { agentApi } from "../../api/modules/agent";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
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
import ChatActionGroup from "../Chat/components/ChatActionGroup";
import ChatHeaderTitle from "../Chat/components/ChatHeaderTitle";
import ChatSessionInitializer from "../Chat/components/ChatSessionInitializer";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import ArtifactPanel from "../Chat/components/ArtifactPanel";
import RunningSessionNotice from "../Chat/components/RunningSessionNotice";
import ExpertTeamStatusStrip from "../Chat/components/ExpertTeamStatusStrip";
import RuntimeProgressCard from "../Chat/components/RuntimeProgressCard";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { planApi } from "../../api/modules/plan";
import PreparingOverlay from "../Chat/components/PreparingOverlay";
import { TaskArtifactCard } from "../Chat/components/TaskArtifactCard";
import { SuperExpertAigcCards } from "../Chat/components/SuperExpertAigcCards";
import { InlineSuperExpertInteractionCards } from "../Chat/components/SuperExpertInteractionCards";
import {
  ATTACHMENT_FILES_CARD,
  AttachmentFilesCard,
  UserRequestCard,
  type UserRequestCardProps,
} from "../../components/UserRequestCard";
import { scheduleArtifactCardScans } from "../Chat/utils/artifactCardScanScheduler";
import { createRoot } from "react-dom/client";
import { shouldRedirectAfterAgentChange } from "./agentRoutePolicy";
import {
  clearPendingTaskIntent,
  loadPendingTaskIntent,
  savePendingTaskIntent,
  type PendingTaskIntent,
} from "../../utils/pendingTaskIntent";

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
} from "../Chat/components/WhisperSpeechButton";

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
} from "../Chat/utils";

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

interface TaskIntent {
  prompt: string;
  agentId: string;
  expertTeam?: ExpertTeamTemplate | null;
}

function normalizeStoredTaskIntent(intent: PendingTaskIntent): TaskIntent {
  return {
    prompt: intent.prompt,
    agentId: intent.agentId,
    expertTeam:
      (intent.expertTeam as ExpertTeamTemplate | null | undefined) ?? null,
  };
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
const TASK_STATUS_POLL_INTERVAL_MS = 2000;
const TASK_STATUS_REQUEST_TIMEOUT_MS = 10_000;
const TERMINAL_TASK_STATUSES = new Set(["completed", "failed", "cancelled"]);

function isGenerationStillRunning(status: {
  status?: string | null;
  task_status?: string | null;
}) {
  return (
    status.status === "running" &&
    !TERMINAL_TASK_STATUSES.has(String(status.task_status || ""))
  );
}

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

export default function ChatPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const { isDark } = useTheme();
  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/(chat|task)\/(.+)$/);
    return match?.[2];
  }, [location.pathname]);
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const [showArtifactPanel, setShowArtifactPanel] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [runtimeReloadKey, setRuntimeReloadKey] = useState(0);
  const [interactionBlocked, setInteractionBlocked] = useState(false);
  const persistedExpertTeamRef = useRef<string>("");
  const {
    selectedAgent,
    selectedExpertTeam,
    currentExpertTeamRun,
    setSelectedExpertTeam,
    setCurrentExpertTeamRun,
  } = useAgentStore();
  const responseIdentity = useExpertIdentity(
    selectedAgent,
    !!selectedExpertTeam,
  );
  const { toolRenderConfig } = usePlugins();
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();
  const { setActiveSessionId } = useRuntimeEvents();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const [planEnabled, setPlanEnabled] = useState(false);

  useEffect(() => {
    const sessionId = chatId && !isDraftSessionId(chatId) ? chatId : null;
    setInteractionBlocked(false);
    setActiveSessionId(sessionId);
    return () => setActiveSessionId(null);
  }, [chatId, setActiveSessionId]);

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
    if (!chatId || isDraftSessionId(chatId)) return;
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
        console.warn("Failed to restore expert team from task:", error);
      }
    };

    void restoreExpertTeam();

    return () => {
      cancelled = true;
    };
  }, [chatId, setCurrentExpertTeamRun, setSelectedExpertTeam]);

  useEffect(() => {
    if (!chatId || isDraftSessionId(chatId) || !selectedExpertTeam) {
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
  }, [chatId, selectedExpertTeam]);

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

          // Re-apply display none in case React stripped it
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
  isChatActiveRef.current = location.pathname.startsWith("/task");

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
      chatId,
      window.currentSessionId,
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
        request.rootSessionId || chatId || window.currentSessionId || "";

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
        request.rootSessionId || chatId || window.currentSessionId || "";

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
      .then((res) => {
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

  // Handle task page entry: show preparing overlay and auto-submit intent.
  //
  // Case 1 (Workbench intent): Navigate state contains { intent: { prompt } }.
  //   We show the overlay, wait for the chat component's submit() to become
  //   available, then programmatically submit the user's message. This uses
  //   the component's native createSession → customFetch → get_or_create_chat
  //   flow, which is the same proven path as manual typing.
  //
  // Case 2 (Direct URL entry): chatId is set from the URL (e.g. /task/UUID).
  //   We show the overlay until existing messages load into the component.
  const hasShownPreparingRef = useRef(false);
  // Track which navigation (by location.key) has been processed, so repeated
  // navigations from Workbench each get their own intent execution — even though
  // the Task page component never unmounts in the SPA.
  const processedLocationKeyRef = useRef<string | null>(null);
  // Capture intent from navigation state into a ref so we can read it once
  // without putting location.state in the dependency array (which would cause
  // the navigate() call below to re-trigger and kill the polling interval).
  const intentRef = useRef<TaskIntent | null>(null);
  const intentSourceRef = useRef<"navigation" | "storage" | null>(null);
  const locState = location.state as {
    intent?: TaskIntent;
  } | null;
  if (locState?.intent && processedLocationKeyRef.current !== location.key) {
    intentRef.current = locState.intent;
    intentSourceRef.current = "navigation";
    if (chatId) {
      savePendingTaskIntent(chatId, locState.intent);
    }
  } else if (
    !locState?.intent &&
    chatId &&
    processedLocationKeyRef.current === null &&
    !intentRef.current
  ) {
    const storedIntent = loadPendingTaskIntent(chatId);
    if (storedIntent) {
      intentRef.current = normalizeStoredTaskIntent(storedIntent);
      intentSourceRef.current = "storage";
    }
  }

  const pendingIntentRef = useRef<{ prompt: string; chatId: string } | null>(
    null,
  );
  const [intentToSubmit, setIntentToSubmit] = useState<{
    prompt: string;
    targetId: string | undefined;
  } | null>(null);
  const processingIntentRef = useRef(false);
  const { currentSessionId } = useChatAnywhereSessionsState();

  useEffect(() => {
    const isTargetMatch =
      intentToSubmit?.targetId === undefined
        ? currentSessionId === undefined
        : true;

    if (intentToSubmit && isTargetMatch && !processingIntentRef.current) {
      processingIntentRef.current = true;
      const prompt = intentToSubmit.prompt;

      let attempts = 0;
      const trySubmit = () => {
        attempts++;
        if (chatRef.current?.input?.submit) {
          try {
            (chatRef.current.input.submit as any)({ query: prompt });
          } catch (err) {
            console.error("[Task] Error submitting intent:", err);
          }
          setIntentToSubmit(null);
          setIsPreparing(false);
          processingIntentRef.current = false;
        } else if (attempts < 40) {
          setTimeout(trySubmit, 50);
        } else {
          console.warn("[Task] Chat input ref not ready after 2s. Aborting.");
          setIntentToSubmit(null);
          setIsPreparing(false);
          processingIntentRef.current = false;
        }
      };

      trySubmit();
    }
  }, [intentToSubmit, currentSessionId]);

  useEffect(() => {
    // Case 1: Intent-driven entry from Workbench
    if (intentRef.current && processedLocationKeyRef.current !== location.key) {
      processedLocationKeyRef.current = location.key;
      hasShownPreparingRef.current = true; // Prevent Case 2 from re-triggering when URL updates to /task/UUID
      setIsPreparing(true);

      const intentPrompt = intentRef.current.prompt;
      const intentExpertTeam = intentRef.current.expertTeam;
      const intentSource = intentSourceRef.current;
      if (intentExpertTeam !== undefined) {
        setSelectedExpertTeam(intentExpertTeam || null);
      }
      intentRef.current = null; // Consumed
      intentSourceRef.current = null;

      let cancelled = false;

      const queueIntentSubmission = () => {
        if (cancelled) return;
        if (chatId) {
          pendingIntentRef.current = { prompt: intentPrompt, chatId };
          const selectedChatId =
            sessionApi.getRealIdForSession(window.currentSessionId || "") ||
            window.currentSessionId;
          if (selectedChatId === chatId) {
            pendingIntentRef.current = null;
            setIntentToSubmit({ prompt: intentPrompt, targetId: chatId });
          }
        } else {
          setIntentToSubmit({ prompt: intentPrompt, targetId: undefined });
        }
      };

      // Clear navigation state to prevent re-submit on page refresh.
      queueMicrotask(() => {
        navigate(location.pathname, { replace: true, state: {} });
      });

      if (chatId && intentSource === "storage") {
        void chatApi
          .getChatStatus(chatId, selectedAgent)
          .then((status) => {
            if (cancelled) return;
            if (status.status === "idle" && status.message_count === 0) {
              queueIntentSubmission();
            } else {
              clearPendingTaskIntent(chatId);
              setIsPreparing(false);
            }
          })
          .catch(() => {
            queueIntentSubmission();
          });
      } else {
        queueIntentSubmission();
      }

      // Safety timeout just in case the event never fires
      const fallbackTimeout = setTimeout(() => {
        if (pendingIntentRef.current) {
          pendingIntentRef.current = null;
          setIsPreparing(false);
        }
      }, 10000);

      return () => {
        cancelled = true;
        clearTimeout(fallbackTimeout);
      };
    }

    // Case 2: Direct URL entry (returning to existing task /task/UUID)
    if (!hasShownPreparingRef.current) {
      hasShownPreparingRef.current = true;
      if (chatId) {
        setIsPreparing(true);

        // We poll up to 4 times (1.2 seconds) to hide the flicker of messages loading.
        // If the chat is actually empty, this will gracefully time out and show the empty state,
        // rather than freezing the UI for 9 seconds.
        let attempts = 0;
        const interval = setInterval(() => {
          attempts++;
          const messages = chatRef.current?.messages?.getMessages?.();
          if ((messages && messages.length > 0) || attempts >= 4) {
            clearInterval(interval);
            setIsPreparing(false);
          }
        }, 300);

        return () => {
          clearInterval(interval);
          setIsPreparing(false);
        };
      }
    }
    // NOTE: location.state is intentionally excluded from deps. The intent
    // is captured into intentRef during render, so the effect only needs to
    // run on mount (and when chatId changes for Case 2).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, location.pathname, navigate]);

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
      navigateRef.current(`/task/${realId}`, { replace: true });
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
        navigateRef.current("/task", { replace: true });
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

      // ----------------------------------------------------
      // MVP FIX: Safely submit intents after React state updates
      if (
        pendingIntentRef.current &&
        pendingIntentRef.current.chatId === targetId
      ) {
        setIntentToSubmit({
          prompt: pendingIntentRef.current.prompt,
          targetId,
        });
        pendingIntentRef.current = null; // consume it
      }
      // ----------------------------------------------------

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
        navigateRef.current(`/task/${targetId}`, { replace: true });
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
        navigateRef.current("/task", { replace: true });
      }
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
      sessionApi.onSessionSelected = null;
      sessionApi.onSessionCreated = null;
    };
  }, []);

  // Setup multimodal capabilities tracking via custom hook

  // Refresh chat when selectedAgent changes, preserving last active chat per agent
  const { setLastChatId, getLastChatId } = useAgentStore();
  const prevSelectedAgentRef = useRef(selectedAgent);

  // ── Synchronous cache reset (MUST run in render phase, NOT in useEffect) ──
  // When selectedAgent changes, key={selectedAgent} on AgentScopeRuntimeWebUI
  // causes React to unmount the old component and mount a new one DURING this
  // render cycle. The new component's mount effects call sessionApi.getSessionList(),
  // so the cache MUST be cleared BEFORE the render completes — otherwise the new
  // component would receive stale sessions from the previous agent's workspace.
  if (
    prevSelectedAgentRef.current !== selectedAgent &&
    prevSelectedAgentRef.current !== undefined
  ) {
    sessionApi.reset();
    lastSessionIdRef.current = null;
  }

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
    let requestSeq = 0;

    const refreshCompletedSession = () => {
      void sessionApi
        .getSession(chatId)
        .catch((error) => {
          console.error("Failed to refresh completed session:", error);
        })
        .finally(() => {
          setRuntimeReloadKey((key) => key + 1);
        });
    };

    const checkGenerationStatus = async (force = false) => {
      if (cancelled || document.visibilityState === "hidden") {
        return;
      }
      const activeChatId = chatIdRef.current || window.currentSessionId;
      if (activeChatId !== chatId) return;
      if (inFlight) {
        if (!force) return;
        controller?.abort();
        inFlight = false;
      }

      const currentRequest = requestSeq + 1;
      requestSeq = currentRequest;
      const nextController = new AbortController();
      controller = nextController;
      const timeout = window.setTimeout(() => {
        nextController.abort();
      }, TASK_STATUS_REQUEST_TIMEOUT_MS);
      try {
        inFlight = true;
        const status = await chatApi.getChatStatus(
          chatId,
          selectedAgent,
          nextController.signal,
        );
        if (cancelled || currentRequest !== requestSeq) return;

        if (!isGenerationStillRunning(status)) {
          setIsGenerating(false);
          refreshCompletedSession();
        }
      } catch (error) {
        if (
          !cancelled &&
          currentRequest === requestSeq &&
          (error as Error).name !== "AbortError"
        ) {
          console.error("Failed to poll chat status:", error);
        }
      } finally {
        window.clearTimeout(timeout);
        if (currentRequest === requestSeq) {
          inFlight = false;
          if (controller === nextController) {
            controller = null;
          }
        }
      }
    };

    const checkRestoredPage = () => {
      if (document.visibilityState === "visible") {
        void checkGenerationStatus(true);
      }
    };

    const timer = window.setInterval(
      () => void checkGenerationStatus(),
      TASK_STATUS_POLL_INTERVAL_MS,
    );
    void checkGenerationStatus();
    document.addEventListener("visibilitychange", checkRestoredPage);
    window.addEventListener("pageshow", checkRestoredPage);
    window.addEventListener("focus", checkRestoredPage);
    window.addEventListener("online", checkRestoredPage);

    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", checkRestoredPage);
      window.removeEventListener("pageshow", checkRestoredPage);
      window.removeEventListener("focus", checkRestoredPage);
      window.removeEventListener("online", checkRestoredPage);
    };
  }, [chatId, isGenerating, selectedAgent]);

  useEffect(() => {
    const prevAgent = prevSelectedAgentRef.current;
    if (
      shouldRedirectAfterAgentChange({
        previousAgent: prevAgent,
        nextAgent: selectedAgent,
        currentChatId: chatIdRef.current,
      })
    ) {
      // Save current chat ID for the agent we're leaving
      const currentChatId =
        chatIdRef.current || lastSessionIdRef.current || undefined;
      if (currentChatId && prevAgent) {
        setLastChatId(prevAgent, currentChatId);
      }

      // We MUST navigate away because the backend isolates chats per agent workspace.
      // A chat from the old agent cannot be continued by the new agent (it will return 404).
      // We start a new chat context for the new agent, or go to their last chat.
      const lastChatId = getLastChatId(selectedAgent);
      if (lastChatId) {
        navigateRef.current(`/task/${lastChatId}`);
      } else {
        navigateRef.current(`/task`);
      }
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
              if (parsed.object === "message" && parsed.content) {
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
            } catch (e) {
              // Ignore invalid JSON chunks
            }
          }
        }
        buffer = lines[lines.length - 1];
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

  const customFetch = useCallback(
    async (data: {
      input?: Array<Record<string, unknown>>;
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const activeExpertTeam =
        useAgentStore.getState().selectedExpertTeam || selectedExpertTeam;
      const requestAgentId = activeExpertTeam?.leader_agent_id || selectedAgent;
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
        channel: window.currentChannel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        ...(activeExpertTeam ? { expert_team_id: activeExpertTeam.id } : {}),
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
            ...(activeExpertTeam
              ? {
                  expert_team_id: activeExpertTeam.id,
                  expert_team_name: activeExpertTeam.name,
                }
              : {}),
          },
        });

        precreatedChatId = createdChat.id;
        if (activeExpertTeam) {
          saveExpertTeamSelectionForChat(createdChat.id, activeExpertTeam.id);
        }
        submittedSessionId = createdChat.session_id || createdChat.id;
        requestBody.session_id = submittedSessionId;
        requestBody.user_id = createdChat.user_id || requestBody.user_id;
        requestBody.channel = createdChat.channel || requestBody.channel;
        sessionApi.recordCreatedChat(createdChat);
        lastSessionIdRef.current = createdChat.id;
        navigateRef.current(`/task/${createdChat.id}`, { replace: true });
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

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      const resolvedChatId =
        response.headers.get("X-QwenPaw-Chat-Id") || precreatedChatId;
      if (response.ok) {
        const startedChatId =
          resolvedChatId || precreatedChatId || backendChatId || routeChatId;
        if (startedChatId) {
          clearPendingTaskIntent(startedChatId);
        }
      }
      if (resolvedChatId && activeExpertTeam) {
        saveExpertTeamSelectionForChat(resolvedChatId, activeExpertTeam.id);
      }
      const expertTeamRunId = response.headers.get(
        "X-QwenPaw-Expert-Team-Run-Id",
      );
      if (expertTeamRunId) {
        setCurrentExpertTeamRun({
          id: expertTeamRunId,
          team_id: activeExpertTeam?.id || "",
          root_chat_id: resolvedChatId || precreatedChatId || "",
          root_session_id: submittedSessionId,
          user_id: String(requestBody.user_id || ""),
          state: "running",
          members:
            activeExpertTeam?.members.map((member) => ({
              id: `${expertTeamRunId}:${member.key}`,
              run_id: expertTeamRunId,
              member_key: member.key,
              agent_id: member.agent_id,
              display_name: member.display_name,
              role: member.role,
              avatar: member.avatar,
              state: "pending",
            })) || [],
          team: activeExpertTeam || null,
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
          navigateRef.current(`/task/${resolvedChatId}`, { replace: true });
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
    [selectedAgent, selectedExpertTeam, setCurrentExpertTeamRun],
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
            <ChatHeaderTitle />
            <span style={{ flex: 1 }} />
            <ChatActionGroup planEnabled={planEnabled} isTaskMode={true} />
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        nick: responseIdentity.name,
        greeting: t("workbench.slogan", "让 AI 为你高效工作"),
        description: t("workbench.subtitle", "随时触发，本地智能完成"),
        avatar: responseIdentity.avatar,
        prompts: [], // Claw 不需要建议按钮
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
              session_id: chatId || window.currentSessionId || data.session_id,
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
        AgentScopeRuntimeRequestCard: (cardProps: UserRequestCardProps) => (
          <UserRequestCard
            {...cardProps}
            chatId={chatId || window.currentSessionId || ""}
            agentId={selectedAgent}
          />
        ),
        [ATTACHMENT_FILES_CARD]: AttachmentFilesCard,
        AgentScopeRuntimeResponseCard: (cardProps: any) => (
          <RuntimeProgressCard
            {...cardProps}
            chatId={chatId || window.currentSessionId || ""}
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
        className={styles.taskView}
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
          {isPreparing && <PreparingOverlay />}
          <div className={styles.chatMessagesArea}>
            <div className={styles.runtimeViewport}>
              <AgentScopeRuntimeWebUI
                key={`${selectedAgent}:${runtimeReloadKey}`}
                options={options}
                ref={chatRef}
              />
            </div>
            {chatId && !isDraftSessionId(chatId) ? (
              <InlineSuperExpertInteractionCards
                conversationId={chatId}
                responseRevision={runtimeReloadKey}
                onBlockingChange={setInteractionBlocked}
                onSubmitAsUserInput={(text) => {
                  (chatRef.current?.input.submit as any)({ query: text });
                }}
              />
            ) : null}
            <WorkbenchInput
              wide
              disabled={interactionBlocked}
              inFlow
              isGenerating={isGenerating}
              topAccessory={
                <>
                  {chatId && !isDraftSessionId(chatId) && (
                    <SuperExpertAigcCards
                      key={chatId}
                      conversationId={chatId}
                      watchForNewCards={isGenerating}
                    />
                  )}
                  <RunningSessionNotice
                    visible={
                      isGenerating && !!chatId && !isDraftSessionId(chatId)
                    }
                    variant="inline"
                  />
                  {(selectedExpertTeam || currentExpertTeamRun) && (
                    <ExpertTeamStatusStrip
                      chatId={chatId}
                      visible
                      variant="composer"
                    />
                  )}
                </>
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
            />
          </div>
        </div>

        {/* Right-side artifact panel */}
        <ArtifactPanel
          visible={showArtifactPanel}
          onToggle={() => setShowArtifactPanel(!showArtifactPanel)}
          chatId={chatId}
        />

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
                  request.rootSessionId ||
                  chatId ||
                  window.currentSessionId ||
                  "";
                const resolvedChatId =
                  sessionApi.getRealIdForSession(sessionId) ??
                  chatIdRef.current ??
                  sessionId;

                if (resolvedChatId) {
                  console.log("[Chat] Calling stopChat with:", resolvedChatId);
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
                style={{ color: isDark ? "rgba(255,255,255,0.88)" : undefined }}
              >
                {t("modelConfig.promptTitle")}
              </span>
            }
            subTitle={
              <span
                style={{ color: isDark ? "rgba(255,255,255,0.55)" : undefined }}
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
    </ExpertIdentityContext.Provider>
  );
}
