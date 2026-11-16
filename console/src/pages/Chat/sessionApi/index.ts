import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, {
  type ChatSpec,
  type ChatHistory,
  type ChatStatus,
  type Message,
} from "../../../api";
import { toDisplayUrl, rewritePayloadMediaUrls } from "../utils";
import {
  clearAllLiveResponseText,
  clearLiveResponseText,
} from "./liveResponseStore";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const DEFAULT_SESSION_NAME = "New Chat";
export const DRAFT_SESSION_ID = "draft-session";
const SESSION_HISTORY_CACHE_TTL_MS = 60_000;
const SESSION_HISTORY_CACHE_MAX_ENTRIES = 8;
const SESSION_HISTORY_REQUEST_TIMEOUT_MS = 15_000;
const ROLE_TOOL = "tool";
const ROLE_USER = "user";
const ROLE_ASSISTANT = "assistant";
const TYPE_PLUGIN_CALL_OUTPUT = "plugin_call_output";
const CARD_RESPONSE = "AgentScopeRuntimeResponseCard";

// ---------------------------------------------------------------------------
// Window globals
// ---------------------------------------------------------------------------

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

// ---------------------------------------------------------------------------
// Local helper types
// ---------------------------------------------------------------------------

/** A single item inside a message's content array. */
interface ContentItem {
  type: string;
  text?: string;
  [key: string]: unknown;
}

/** A backend message after role-normalisation (output of toOutputMessage). */
interface OutputMessage extends Omit<Message, "role"> {
  role: string;
  metadata: unknown;
  sequence_number?: number;
}

/**
 * Extended session carrying extra fields that the library type does not define
 * but our backend / window globals require.
 */
interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  /** Session identifier (channel:user_id format) */
  sessionId: string;
  /** User identifier */
  userId: string;
  /** Channel name */
  channel: string;
  /** Additional metadata */
  meta: Record<string, unknown>;
  /** Real backend UUID, used when id is overridden with a local timestamp. */
  realId?: string;
  /** Conversation status from backend. */
  status?: ChatStatus;
  /** ISO 8601 creation timestamp from backend. */
  createdAt?: string | null;
  /** ISO 8601 update timestamp used to invalidate restored-history cache. */
  updatedAt?: string | null;
  /** Whether the backend is still generating a response for this session. */
  generating?: boolean;
  /** Whether the chat is pinned to the top. */
  pinned?: boolean;
}

interface HistoryCacheEntry {
  history: ChatHistory;
  cachedAt: number;
  updatedAt: string | null;
}

function cloneChatHistory(history: ChatHistory): ChatHistory {
  return structuredClone(history);
}

// ---------------------------------------------------------------------------
// Message conversion helpers: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

export function isDraftSessionId(sessionId?: string | null): boolean {
  return !sessionId || sessionId === DRAFT_SESSION_ID;
}

function getRouteSessionId(): string | null {
  const match = window.location.pathname.match(
    /^\/(?:chat|task|claw)\/([^/?#]+)/,
  );
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** Extract plain text from a message's content array. */
const extractTextFromContent = (content: unknown): string => {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return String(content || "");
  return (content as ContentItem[])
    .filter((c) => c.type === "text")
    .map((c) => c.text || "")
    .filter(Boolean)
    .join("\n");
};

export function stripSkillInvocationPrefix(text: string): string {
  const expandedSkillMatch = text.match(
    /Use the \[[^\]\r\n]+\] skill in `[^`]+` to fulfill user's task:\s*([^\r\n]+)/u,
  );
  if (expandedSkillMatch?.[1]) {
    return expandedSkillMatch[1].trim();
  }

  return text.replace(/^\s*\/\[[^\]\r\n]+\]\s*(?:\r?\n\s*)*/u, "");
}

function resolveContentItemUrl(c: ContentItem): ContentItem {
  if (c.type === "image" && c.image_url) {
    return { ...c, image_url: toDisplayUrl(c.image_url as string) };
  }
  if (c.type === "audio" && c.data) {
    return { ...c, data: toDisplayUrl(c.data as string) };
  }
  if (c.type === "video" && c.video_url) {
    return { ...c, video_url: toDisplayUrl(c.video_url as string) };
  }
  if (c.type === "file" && (c.file_url || c.file_id)) {
    return {
      ...c,
      file_url: toDisplayUrl((c.file_url as string) || (c.file_id as string)),
      file_name: (c.filename as string) || (c.file_name as string) || "file",
    };
  }
  return c;
}

/** Map backend message content to request card content (text + image + file). */
function contentToRequestParts(
  content: unknown,
): Array<Record<string, unknown>> {
  if (typeof content === "string") {
    return [
      {
        type: "text",
        text: stripSkillInvocationPrefix(content),
        status: "created",
      },
    ];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content || ""), status: "created" }];
  }
  let strippedFirstText = false;
  const parts = (content as ContentItem[])
    .map(resolveContentItemUrl)
    .map((c) => {
      if (
        strippedFirstText ||
        c.type !== "text" ||
        typeof c.text !== "string"
      ) {
        return c;
      }
      strippedFirstText = true;
      return { ...c, text: stripSkillInvocationPrefix(c.text) };
    })
    .map((c) => ({ ...c, status: "created" }));

  if (parts.length === 0) {
    return [{ type: "text", text: "", status: "created" }];
  }

  return parts;
}
function normalizeOutputMessageContent(content: unknown): unknown {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }
  if (!Array.isArray(content)) return content;
  return (content as ContentItem[]).map((c) =>
    c.type === "text" ? { ...c, status: c.status || "created" } : c,
  );
}

/**
 * Convert a backend message to a response output message.
 * Maps system + plugin_call_output → role "tool" and strips metadata.
 */
const toOutputMessage = (msg: Message): OutputMessage => ({
  ...msg,
  role:
    msg.type === TYPE_PLUGIN_CALL_OUTPUT && msg.role === "system"
      ? ROLE_TOOL
      : msg.role,
  metadata: msg.metadata ?? null,
});

/** Build a user card (AgentScopeRuntimeRequestCard) from a user message. */
function buildUserCard(msg: Message): IAgentScopeRuntimeWebUIMessage {
  const contentParts = contentToRequestParts(msg.content);
  return {
    id: (msg.id as string) || generateId(),
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          input: [
            {
              role: "user",
              type: "message",
              content: contentParts,
            },
          ],
        },
      },
    ],
  };
}

/**
 * Build an assistant response card (AgentScopeRuntimeResponseCard)
 * wrapping a group of consecutive non-user output messages.
 */
const buildResponseCard = (
  outputMessages: OutputMessage[],
): IAgentScopeRuntimeWebUIMessage => {
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );

  const normalizedMessages = outputMessages.map((msg) => ({
    ...msg,
    content: normalizeOutputMessageContent(msg.content),
  }));

  return {
    id: generateId(),
    role: ROLE_ASSISTANT,
    cards: [
      {
        code: CARD_RESPONSE,
        data: {
          id: `response_${generateId()}`,
          output: normalizedMessages,
          object: "response",
          status: "completed",
          created_at: now,
          sequence_number: maxSeq + 1,
          error: null,
          completed_at: now,
          usage: null,
        },
      },
    ],
    msgStatus: "finished",
  };
};

/**
 * Convert flat backend messages into the card-based format expected by
 * the @agentscope-ai/chat component.
 *
 * - User messages → AgentScopeRuntimeRequestCard
 * - Consecutive non-user messages (assistant / system / tool) → grouped
 *   into a single AgentScopeRuntimeResponseCard with all output messages.
 */
const convertMessages = (
  messages: Message[],
): IAgentScopeRuntimeWebUIMessage[] => {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let i = 0;

  while (i < messages.length) {
    if (messages[i].role === ROLE_USER) {
      result.push(buildUserCard(messages[i++]));
    } else {
      const outputMsgs: OutputMessage[] = [];
      while (i < messages.length && messages[i].role !== ROLE_USER) {
        outputMsgs.push(toOutputMessage(messages[i++]));
      }
      if (outputMsgs.length) result.push(buildResponseCard(outputMsgs));
    }
  }

  return result;
};

const chatSpecToSession = (chat: ChatSpec): ExtendedSession =>
  ({
    id: chat.id,
    name: chat.name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
    status: chat.status ?? "idle",
    generating: chat.status === "running",
    createdAt: chat.created_at ?? null,
    updatedAt: chat.updated_at ?? null,
    pinned: chat.pinned ?? false,
  }) as ExtendedSession;

/** Returns true when id is a pure numeric local timestamp (not a backend UUID). */
const isLocalTimestamp = (id: string): boolean => /^\d+$/.test(id);

/** Detect if backend is still generating content for this chat. */
const isGenerating = (chatHistory: ChatHistory): boolean => {
  if (chatHistory.status === "running") return true;
  if (chatHistory.status === "idle") return false;
  const msgs = chatHistory.messages || [];
  if (msgs.length === 0) return false;
  const last = msgs[msgs.length - 1];
  return last.role === ROLE_USER;
};

function messagesBeforeRunningResponse(messages: Message[]): Message[] {
  let lastUserIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === ROLE_USER) {
      lastUserIndex = index;
      break;
    }
  }
  return lastUserIndex >= 0 ? messages.slice(0, lastUserIndex + 1) : [];
}

const isChatNotFoundError = (error: unknown): boolean =>
  error instanceof Error && /^Chat not found\b/.test(error.message);

const isAbortError = (error: unknown): boolean =>
  typeof error === "object" &&
  error !== null &&
  "name" in error &&
  error.name === "AbortError";

/**
 * Resolve and persist the real backend UUID for a local timestamp session.
 * Stores the real UUID as realId while keeping the timestamp as id, so the
 * library's internal currentSessionId (timestamp) remains valid.
 * Returns the resolved real UUID, or null if not found.
 */
const resolveRealId = (
  sessionList: IAgentScopeRuntimeWebUISession[],
  tempSessionId: string,
): { list: IAgentScopeRuntimeWebUISession[]; realId: string | null } => {
  // 1) Exact match: a session whose id already equals the temp timestamp
  //    (e.g. after applyChatsToSessionList merged it).
  let realSession = sessionList.find((s) => s.id === tempSessionId);

  // 2) Fallback: match by sessionId, but only consider sessions that have
  //    NOT yet been resolved (no realId) to avoid stealing another session's
  //    backend UUID — same class of bug as #3843.
  if (!realSession) {
    realSession = sessionList.find(
      (s) =>
        (s as ExtendedSession).sessionId === tempSessionId &&
        !(s as ExtendedSession).realId,
    );
  }

  if (!realSession) return { list: sessionList, realId: null };

  const realUUID = realSession.id;
  (realSession as ExtendedSession).realId = realUUID;
  realSession.id = realUUID; // KEEPS realUUID so library session list updates
  return {
    list: [realSession, ...sessionList.filter((s) => s !== realSession)],
    realId: realUUID,
  };
};

// ---------------------------------------------------------------------------
// Per-session user message persistence (survives page refresh)
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = "qwenpaw_pending_user_msg_";

function savePendingUserMessage(sessionId: string, text: string): void {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${sessionId}`, text);
  } catch {
    /* quota exceeded – ignore */
  }
}

function loadPendingUserMessage(sessionId: string): string {
  try {
    return sessionStorage.getItem(`${STORAGE_PREFIX}${sessionId}`) || "";
  } catch {
    return "";
  }
}

function clearPendingUserMessage(sessionId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${sessionId}`);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// SessionApi
// ---------------------------------------------------------------------------

class SessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private sessionList: IAgentScopeRuntimeWebUISession[] = [];

  /** Completed histories only; running conversations must always be restored live. */
  private historyCache: Map<string, HistoryCacheEntry> = new Map();

  /** In-flight detail requests, so switching conversations can cancel stale work. */
  private sessionLoadControllers: Map<string, AbortController> = new Map();

  /** Latest requested session; stale loaders resolve to this request after cancellation. */
  private latestRequestedSessionId: string | null = null;

  /**
   * Pending resolvers waiting for a specific session's realId.
   * Used to replace setTimeout-based busy-wait with event-driven notification.
   */
  private realIdResolvers: Map<string, Array<() => void>> = new Map();

  /** Notify any pending waiters that a session's realId has been resolved. */
  private notifyRealIdResolved(sessionId: string): void {
    const resolvers = this.realIdResolvers.get(sessionId);
    if (resolvers) {
      this.realIdResolvers.delete(sessionId);
      for (const resolve of resolvers) resolve();
    }
  }

  /** Wait until a session's realId is available (set by updateSession). */
  private waitForRealId(sessionId: string): Promise<void> {
    const session = this.sessionList.find((x) => x.id === sessionId) as
      | ExtendedSession
      | undefined;
    if (session?.realId) return Promise.resolve();

    return new Promise<void>((resolve) => {
      const existing = this.realIdResolvers.get(sessionId) || [];
      existing.push(resolve);
      this.realIdResolvers.set(sessionId, existing);
    });
  }

  /**
   * Clear all internal caches so the next getSessionList / getSession call
   * fetches fresh data from the backend.  Must be called when the active
   * agent changes, because sessions are isolated per agent workspace and
   * the singleton would otherwise serve stale data from the previous agent.
   */
  reset(): void {
    for (const controller of this.sessionLoadControllers.values()) {
      controller.abort();
    }
    this.sessionList = [];
    this.historyCache.clear();
    this.sessionLoadControllers.clear();
    this.realIdResolvers.clear();
    this.sessionListRequest = null;
    this.sessionRequests.clear();
    this.latestRequestedSessionId = null;
    this.lastSelectedSessionId = null;
    this.preferredChatId = null;
    window.currentSessionId = undefined;
    clearAllLiveResponseText();
  }

  /**
   * When set, getSessionList will move the matching session to the front on the first call,
   * so the library's useMount auto-selects it instead of always defaulting to sessions[0].
   * Cleared after first use.
   */
  preferredChatId: string | null = null;

  /**
   * Cache the latest user message for a chat so it can be patched into
   * history during reconnect (the backend only persists it after generation
   * completes). Persisted to sessionStorage so it survives page refresh.
   */
  setLastUserMessage(sessionId: string, text: string): void {
    if (!sessionId || !text) return;
    this.invalidateHistoryCache(sessionId);
    savePendingUserMessage(sessionId, text);
  }

  private invalidateHistoryCache(sessionId: string): void {
    this.historyCache.delete(sessionId);
    const session = this.sessionList.find((item) => {
      const extended = item as ExtendedSession;
      return (
        item.id === sessionId ||
        extended.realId === sessionId ||
        extended.sessionId === sessionId
      );
    }) as ExtendedSession | undefined;
    if (!session) return;
    this.historyCache.delete(session.id);
    if (session.realId) this.historyCache.delete(session.realId);
    if (session.sessionId) this.historyCache.delete(session.sessionId);
  }

  private getCachedHistory(
    backendId: string,
    listEntry: ExtendedSession | undefined,
  ): ChatHistory | null {
    const cached = this.historyCache.get(backendId);
    if (!cached) return null;

    const expired = Date.now() - cached.cachedAt > SESSION_HISTORY_CACHE_TTL_MS;
    const statusChanged =
      listEntry?.generating || listEntry?.status === "running";
    const updated =
      Boolean(listEntry?.updatedAt) &&
      Boolean(cached.updatedAt) &&
      listEntry?.updatedAt !== cached.updatedAt;
    if (expired || statusChanged || updated) {
      this.historyCache.delete(backendId);
      return null;
    }
    return cloneChatHistory(cached.history);
  }

  private cacheHistory(
    backendId: string,
    history: ChatHistory,
    listEntry: ExtendedSession | undefined,
  ): void {
    this.historyCache.delete(backendId);
    if (this.historyCache.size >= SESSION_HISTORY_CACHE_MAX_ENTRIES) {
      const oldestKey = this.historyCache.keys().next().value;
      if (oldestKey) this.historyCache.delete(oldestKey);
    }
    this.historyCache.set(backendId, {
      history: cloneChatHistory(history),
      cachedAt: Date.now(),
      updatedAt: listEntry?.updatedAt ?? null,
    });
  }

  private cancelOtherSessionLoads(sessionId: string): void {
    for (const [activeSessionId, controller] of this.sessionLoadControllers) {
      if (activeSessionId === sessionId) continue;
      controller.abort();
      this.sessionLoadControllers.delete(activeSessionId);
    }
  }

  /**
   * Deduplicates concurrent getSessionList calls so that two parallel
   * invocations share one network request and write sessionList only once,
   * preserving any realId mappings that were already resolved.
   */
  private sessionListRequest: Promise<IAgentScopeRuntimeWebUISession[]> | null =
    null;

  /**
   * Deduplicates concurrent getSession calls for the same sessionId.
   * Key: sessionId, Value: in-flight promise for getSession.
   */
  private sessionRequests: Map<
    string,
    Promise<IAgentScopeRuntimeWebUISession>
  > = new Map();

  /**
   * Called when a temporary timestamp session id is resolved to a real backend
   * UUID. Consumers (e.g. Chat/index.tsx) can register here to update the URL.
   */
  onSessionIdResolved: ((tempId: string, realId: string) => void) | null = null;

  /**
   * Called after a session is removed. Consumers can register here to clear
   * the session id from the URL.
   */
  onSessionRemoved: ((removedId: string) => void) | null = null;

  /**
   * Called when a session is selected from the session list.
   * Consumers can register here to update the URL when switching sessions.
   */
  onSessionSelected:
    | ((sessionId: string | null | undefined, realId: string | null) => void)
    | null = null;

  /** Called around history restoration so the task view can show stable feedback. */
  onSessionLoadStart: ((sessionId: string) => void) | null = null;
  onSessionLoadEnd:
    | ((sessionId: string, error: unknown | null) => void)
    | null = null;

  /**
   * Called when a new session is created.
   * Consumers can register here to update the URL with the new session id.
   */
  onSessionCreated: ((sessionId: string) => void) | null = null;

  /**
   * When reconnecting to a running conversation, the backend history may not
   * include the latest user message (it's only persisted after generation
   * completes). If generating, look up the cached text from sessionStorage
   * and patch it into the message list.
   *
   * When not generating the conversation is done — clear the cached entry.
   */
  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): void {
    if (!generating) {
      clearPendingUserMessage(backendSessionId);
      return;
    }

    const cachedText = loadPendingUserMessage(backendSessionId);
    if (!cachedText) return;

    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === ROLE_USER) {
      const text = extractTextFromContent(
        lastMsg?.cards?.[0]?.data?.input?.[0]?.content,
      );
      if (!text) {
        lastMsg.cards = buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message).cards;
      }
    } else {
      messages.push(
        buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message),
      );
    }
  }

  private createEmptySession(sessionId: string): ExtendedSession {
    window.currentSessionId = sessionId;
    window.currentUserId = DEFAULT_USER_ID;
    window.currentChannel = DEFAULT_CHANNEL;
    return {
      id: sessionId,
      name: DEFAULT_SESSION_NAME,
      sessionId,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    } as ExtendedSession;
  }

  private createDraftSession(): ExtendedSession {
    const isClawMode = window.location.pathname.startsWith("/claw");
    window.currentSessionId = undefined;
    window.currentUserId = DEFAULT_USER_ID;
    window.currentChannel = isClawMode ? "claw" : DEFAULT_CHANNEL;
    return {
      id: DRAFT_SESSION_ID,
      name: DEFAULT_SESSION_NAME,
      sessionId: DRAFT_SESSION_ID,
      userId: DEFAULT_USER_ID,
      channel: isClawMode ? "claw" : DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    } as ExtendedSession;
  }

  private updateWindowVariables(session: ExtendedSession): void {
    window.currentSessionId = session.sessionId || "";
    window.currentUserId = session.userId || DEFAULT_USER_ID;
    window.currentChannel = session.channel || DEFAULT_CHANNEL;
  }

  private getLocalSession(sessionId: string): IAgentScopeRuntimeWebUISession {
    const local = this.sessionList.find((s) => s.id === sessionId);
    if (local) {
      this.updateWindowVariables(local as ExtendedSession);
      return local;
    }
    return this.createEmptySession(sessionId);
  }

  /**
   * Returns the real backend UUID for a session identified by id (which may be
   * a local timestamp). Returns null when not yet resolved or not found.
   */
  getRealIdForSession(sessionId: string): string | null {
    const s = this.sessionList.find((x) => {
      const ext = x as ExtendedSession;
      return (
        x.id === sessionId ||
        ext.realId === sessionId ||
        ext.sessionId === sessionId
      );
    }) as ExtendedSession | undefined;
    return s?.realId ?? null;
  }

  private findSessionByChatId(chatId: string): ExtendedSession | undefined {
    return this.sessionList.find((s) => {
      const ext = s as ExtendedSession;
      return s.id === chatId || ext.realId === chatId;
    }) as ExtendedSession | undefined;
  }

  private removeMissingSession(
    displayId: string,
    backendId = displayId,
  ): ExtendedSession {
    this.invalidateHistoryCache(displayId);
    this.invalidateHistoryCache(backendId);
    this.sessionList = this.sessionList.filter((session) => {
      const extended = session as ExtendedSession;
      return (
        session.id !== displayId &&
        session.id !== backendId &&
        extended.realId !== displayId &&
        extended.realId !== backendId &&
        extended.sessionId !== displayId &&
        extended.sessionId !== backendId
      );
    });
    this.onGeneratingStatusChange?.(false);
    clearPendingUserMessage(displayId);
    clearPendingUserMessage(backendId);
    clearLiveResponseText(displayId);
    clearLiveResponseText(backendId);
    this.onSessionRemoved?.(displayId);
    return this.createDraftSession();
  }

  async getSessionIdForChatId(chatId: string): Promise<string | null> {
    if (!chatId || isDraftSessionId(chatId)) return null;

    let session = this.findSessionByChatId(chatId);
    if (!session) {
      if (this.sessionListRequest) {
        await this.sessionListRequest;
      } else {
        await this.getSessionList();
      }
      session = this.findSessionByChatId(chatId);
    }

    return session?.sessionId || chatId;
  }

  /**
   * Record the backend UUID returned by the streaming submit response.
   *
   * This avoids waiting for a later list refresh to infer the mapping from
   * session_id, which is the fragile part of the old placeholder flow.
   */
  resolveSubmittedSession(sessionId: string, realId: string): void {
    if (!sessionId || !realId || sessionId === realId) return;

    const existingIndex = this.sessionList.findIndex(
      (s) =>
        s.id === sessionId ||
        (s as ExtendedSession).realId === sessionId ||
        (s as ExtendedSession).sessionId === sessionId,
    );

    if (existingIndex >= 0) {
      const existing = this.sessionList[existingIndex] as ExtendedSession;
      this.sessionList[existingIndex] = {
        ...existing,
        realId,
      } as IAgentScopeRuntimeWebUISession;
    } else {
      const isClawMode = window.location.pathname.startsWith("/claw");
      this.sessionList.unshift({
        id: sessionId,
        name: DEFAULT_SESSION_NAME,
        sessionId,
        userId: DEFAULT_USER_ID,
        channel: isClawMode ? "claw" : DEFAULT_CHANNEL,
        messages: [],
        meta: {},
        realId,
      } as ExtendedSession);
    }

    this.notifyRealIdResolved(sessionId);
    if (window.currentSessionId === sessionId) {
      window.currentSessionId = realId;
    }
  }

  recordCreatedChat(chat: ChatSpec): void {
    const created = chatSpecToSession(chat) as ExtendedSession;
    const existingIndex = this.sessionList.findIndex(
      (s) => s.id === chat.id || (s as ExtendedSession).realId === chat.id,
    );

    if (existingIndex >= 0) {
      this.sessionList[existingIndex] = {
        ...this.sessionList[existingIndex],
        ...created,
      } as IAgentScopeRuntimeWebUISession;
    } else {
      this.sessionList.unshift(created);
    }

    this.updateWindowVariables(created);
  }

  startDraftSession(): IAgentScopeRuntimeWebUISession[] {
    window.currentSessionId = undefined;
    window.currentUserId = DEFAULT_USER_ID;
    window.currentChannel = window.location.pathname.startsWith("/claw")
      ? "claw"
      : DEFAULT_CHANNEL;
    this.onSessionCreated?.(DRAFT_SESSION_ID);
    return [...this.sessionList];
  }

  /** Apply listChats to sessionList; merge realId by session_id. */
  private applyChatsToSessionList(
    chats: ChatSpec[],
  ): IAgentScopeRuntimeWebUISession[] {
    const newList = chats
      .filter((c) => c.id && c.id !== "undefined" && c.id !== "null")
      .map(chatSpecToSession)
      .reverse();

    // Track which existing sessions have already been matched so that
    // sessions sharing the same sessionId (channel:user_id) don't all
    // resolve to the same existing entry — the root cause of #3843.
    const matchedExistingIds = new Set<string>();

    this.sessionList = newList.map((s) => {
      const sExt = s as ExtendedSession;

      // 1) Exact match by backend UUID: s.id matches existing.id or existing.realId
      let existing = this.sessionList.find((e) => {
        if (matchedExistingIds.has(e.id)) return false;
        const eExt = e as ExtendedSession;
        return e.id === s.id || (eExt.realId != null && eExt.realId === s.id);
      }) as ExtendedSession | undefined;

      // 2) Fallback: match by sessionId, but only claim the first unmatched one
      if (!existing) {
        existing = this.sessionList.find((e) => {
          if (matchedExistingIds.has(e.id)) return false;
          return (e as ExtendedSession).sessionId === sExt.sessionId;
        }) as ExtendedSession | undefined;
      }

      if (!existing) return s;

      matchedExistingIds.add(existing.id);

      const next = { ...s } as ExtendedSession;
      if (existing.realId) {
        next.realId = existing.realId;
        if (!isLocalTimestamp(existing.id)) {
          next.id = existing.id;
        }
      }
      return next as IAgentScopeRuntimeWebUISession;
    });
    if (this.preferredChatId) {
      const preferredId = this.preferredChatId;
      this.preferredChatId = null;
      const idx = this.sessionList.findIndex((s) => s.id === preferredId);
      if (idx > 0) {
        const [preferred] = this.sessionList.splice(idx, 1);
        this.sessionList.unshift(preferred);
      }
    }
    return [...this.sessionList];
  }

  async getSessionList() {
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        const chats = await api.listChats();
        const chatArray = Array.isArray(chats) ? chats : [];

        // Isolate sessions based on current URL route
        const isClawMode = window.location.pathname.startsWith("/claw");
        const filteredChats = chatArray.filter((c) => {
          const isClawChat =
            c.id === "claw-global-session" ||
            c.channel === "claw" ||
            (c.meta &&
              typeof c.meta === "object" &&
              (c.meta as any).mode === "claw");

          return isClawMode ? isClawChat : !isClawChat;
        });

        return this.applyChatsToSessionList(filteredChats);
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  /** Callback fired when the generating status of the current session changes (e.g. after refresh). */
  public onGeneratingStatusChange?: (generating: boolean) => void;

  /** Track the last session ID that triggered onSessionSelected to avoid duplicate calls. */
  private lastSelectedSessionId: string | null = null;

  async getSession(sessionId: string) {
    this.latestRequestedSessionId = sessionId;
    this.cancelOtherSessionLoads(sessionId);
    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) return existingRequest;

    this.onSessionLoadStart?.(sessionId);
    const requestPromise = this._doGetSession(sessionId);
    this.sessionRequests.set(sessionId, requestPromise);

    let loadError: unknown | null = null;
    try {
      let session: IAgentScopeRuntimeWebUISession;
      try {
        session = await requestPromise;
      } catch (error) {
        const replacementId = this.latestRequestedSessionId;
        const replacementRequest = replacementId
          ? this.sessionRequests.get(replacementId)
          : undefined;
        if (
          isAbortError(error) &&
          replacementId !== sessionId &&
          replacementRequest
        ) {
          return await replacementRequest;
        }
        throw error;
      }
      const fellBackToDraft =
        sessionId !== DRAFT_SESSION_ID && session.id === DRAFT_SESSION_ID;
      if (fellBackToDraft) return session;

      // Trigger onSessionSelected only when session actually changes
      if (sessionId !== this.lastSelectedSessionId) {
        this.lastSelectedSessionId = sessionId;
        const extendedSession = session as ExtendedSession;
        const realId = extendedSession.realId || null;
        this.onSessionSelected?.(sessionId, realId);
      }
      return session;
    } catch (error) {
      loadError = error;
      throw error;
    } finally {
      this.sessionRequests.delete(sessionId);
      this.onSessionLoadEnd?.(sessionId, loadError);
    }
  }

  /**
   * Fetch chat history from backend and build an ExtendedSession.
   * Centralises the repeated fetch-convert-patch-build pattern used by
   * _doGetSession in multiple branches.
   */
  private async fetchAndBuildSession(
    displayId: string,
    backendId: string,
    listEntry: ExtendedSession | undefined,
  ): Promise<ExtendedSession> {
    let chatHistory = this.getCachedHistory(backendId, listEntry);
    if (!chatHistory) {
      const controller = new AbortController();
      this.sessionLoadControllers.set(displayId, controller);
      let timedOut = false;
      const timeout = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, SESSION_HISTORY_REQUEST_TIMEOUT_MS);
      try {
        chatHistory = await api.getChat(
          backendId,
          undefined,
          controller.signal,
        );
      } catch (error) {
        if (timedOut) {
          throw new Error("Conversation history request timed out");
        }
        if (!isChatNotFoundError(error)) throw error;

        return this.removeMissingSession(displayId, backendId);
      } finally {
        window.clearTimeout(timeout);
        if (this.sessionLoadControllers.get(displayId) === controller) {
          this.sessionLoadControllers.delete(displayId);
        }
      }

      if (!isGenerating(chatHistory)) {
        this.cacheHistory(backendId, chatHistory, listEntry);
      }
    }
    const generating = isGenerating(chatHistory);
    this.onGeneratingStatusChange?.(generating);

    const backendMessages = chatHistory.messages || [];
    // Rewrite all media URLs inside the history payload before conversion.
    if (backendMessages.length) {
      const historyAgentId =
        typeof listEntry?.meta?.agent_id === "string"
          ? listEntry.meta.agent_id
          : undefined;
      rewritePayloadMediaUrls(backendMessages, displayId, historyAgentId);
    }
    const displayMessages = generating
      ? messagesBeforeRunningResponse(backendMessages)
      : backendMessages;
    const messages = convertMessages(displayMessages);
    this.patchLastUserMessage(messages, generating, backendId);
    if (!generating) {
      clearLiveResponseText(displayId);
      clearLiveResponseText(backendId);
    }

    const session: ExtendedSession = {
      id: displayId,
      name: listEntry?.name || DEFAULT_SESSION_NAME,
      sessionId: listEntry?.sessionId || displayId,
      userId: listEntry?.userId || DEFAULT_USER_ID,
      channel: listEntry?.channel || DEFAULT_CHANNEL,
      messages,
      meta: listEntry?.meta || {},
      realId: listEntry?.realId,
      generating,
    };
    this.updateWindowVariables(session);
    return session;
  }

  private async _doGetSession(
    sessionId: string,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    // --- Local timestamp ID (New Chat before first reply) ---
    if (isDraftSessionId(sessionId)) {
      return this.createDraftSession();
    }

    if (isLocalTimestamp(sessionId)) {
      const fromList = this.sessionList.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;

      // If realId is already resolved, use it directly to fetch history.
      if (fromList?.realId) {
        return this.fetchAndBuildSession(sessionId, fromList.realId, fromList);
      }

      // Pure local session (not yet sent to backend): wait until updateSession
      // resolves the realId, then fetch history with the real UUID.
      await this.waitForRealId(sessionId);

      const refreshed = this.sessionList.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;
      if (refreshed?.realId) {
        return this.fetchAndBuildSession(
          sessionId,
          refreshed.realId,
          refreshed,
        );
      }

      return this.getLocalSession(sessionId);
    }

    // --- No session selected (e.g. after delete) ---
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return this.createDraftSession();
    }

    // --- Regular backend UUID ---
    let fromList = this.sessionList.find(
      (s) => s.id === sessionId || (s as ExtendedSession).realId === sessionId,
    ) as ExtendedSession | undefined;

    if (!fromList) {
      if (this.sessionListRequest) {
        await this.sessionListRequest;
      } else {
        await this.getSessionList();
      }
      fromList = this.sessionList.find(
        (s) =>
          s.id === sessionId || (s as ExtendedSession).realId === sessionId,
      ) as ExtendedSession | undefined;
    }

    // The sidebar list may be stale or still scoped to the previous agent.
    // Only the authenticated detail endpoint can confirm that a deep link is missing.
    const loaded = await this.fetchAndBuildSession(
      sessionId,
      sessionId,
      fromList,
    );
    if (
      !fromList &&
      !isDraftSessionId(loaded.id) &&
      !this.sessionList.some((session) => session.id === loaded.id)
    ) {
      this.sessionList.unshift(loaded);
    }
    return loaded;
  }

  /**
   * After fetching the latest session list, try to resolve a local timestamp
   * session to its real backend UUID and notify listeners.
   */
  private resolveAndNotify(tempId: string): void {
    const { list, realId } = resolveRealId(this.sessionList, tempId);
    this.sessionList = list;
    if (realId) {
      this.notifyRealIdResolved(tempId);
      this.onSessionIdResolved?.(tempId, realId);
    }
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.messages = [];
    const index = this.sessionList.findIndex((s) => s.id === session.id);

    if (index > -1) {
      this.sessionList[index] = { ...this.sessionList[index], ...session };

      const existing = this.sessionList[index] as ExtendedSession;
      if (isLocalTimestamp(existing.id) && !existing.realId) {
        const tempId = existing.id;
        this.getSessionList().then(() => this.resolveAndNotify(tempId));
      }
    } else {
      const tempId = session.id!;
      await this.getSessionList().then(() => this.resolveAndNotify(tempId));
    }

    return [...this.sessionList];
  }

  async createSession(_session: Partial<IAgentScopeRuntimeWebUISession>) {
    // Wait for session list to load so the guard has accurate data
    if (this.sessionListRequest) {
      await this.sessionListRequest;
    } else if (this.sessionList.length === 0) {
      await this.getSessionList();
    }

    // Guard: If an existing session is already active, do NOT create a new one.
    // This prevents the library's ensureSession() from spawning a duplicate
    // when getCurrentSessionId() temporarily returns undefined due to a
    // re-render race condition between session list refresh and ChatSessionInitializer.
    const existingId = window.currentSessionId;
    if (
      existingId &&
      this.sessionList.some(
        (s) =>
          s.id === existingId ||
          (s as ExtendedSession).realId === existingId ||
          (s as ExtendedSession).sessionId === existingId,
      )
    ) {
      return [...this.sessionList];
    }

    const routeSessionId = getRouteSessionId();
    if (routeSessionId && !isDraftSessionId(routeSessionId)) {
      const routeSession = this.sessionList.find((s) => {
        const ext = s as ExtendedSession;
        return (
          s.id === routeSessionId ||
          ext.realId === routeSessionId ||
          ext.sessionId === routeSessionId
        );
      }) as ExtendedSession | undefined;

      if (routeSession) {
        this.updateWindowVariables(routeSession);
      } else {
        await this.getSession(routeSessionId);
      }

      return [...this.sessionList];
    }

    return this.startDraftSession();
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this.sessionList];

    const { id: sessionId } = session;
    this.invalidateHistoryCache(sessionId);

    const existing = this.sessionList.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    const deleteId =
      existing?.realId ?? (isLocalTimestamp(sessionId) ? null : sessionId);

    if (deleteId) await api.deleteChat(deleteId);

    this.sessionList = this.sessionList.filter((s) => s.id !== sessionId);

    const resolvedId = existing?.realId ?? sessionId;
    this.onSessionRemoved?.(resolvedId);

    return [...this.sessionList];
  }
}

export default new SessionApi();
