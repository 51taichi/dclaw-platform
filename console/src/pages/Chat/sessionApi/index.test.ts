import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSpec } from "../../../api";
import sessionApi, {
  DEFAULT_LOCAL_ACCESS_MODE,
  DRAFT_SESSION_ID,
} from "./index";
import { appendLiveResponseText } from "./liveResponseStore";

const { mockListChats, mockGetChat, mockGetPushMessages, mockUpdateChat } =
  vi.hoisted(() => ({
    mockListChats: vi.fn<() => Promise<ChatSpec[]>>(() => Promise.resolve([])),
    mockGetChat: vi.fn(),
    mockGetPushMessages: vi.fn(),
    mockUpdateChat: vi.fn(),
  }));

vi.mock("../../../api", () => ({
  default: {
    listChats: mockListChats,
    getChat: mockGetChat,
    updateChat: mockUpdateChat,
    deleteChat: vi.fn(),
  },
}));

vi.mock("../../../api/modules/console", () => ({
  consoleApi: {
    getPushMessages: mockGetPushMessages,
  },
}));

const makeChatSpec = (
  id: string,
  overrides: Partial<ChatSpec> = {},
): ChatSpec => ({
  id,
  name: `${id} name`,
  session_id: id,
  user_id: "default",
  channel: "console",
  created_at: null,
  updated_at: null,
  meta: {},
  ...overrides,
});

describe("Chat sessionApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetChat.mockReset();
    sessionApi.reset();
    sessionApi.onSessionRemoved = null;
    sessionApi.onSessionSelected = null;
    window.history.pushState({}, "", "/");
    mockListChats.mockResolvedValue([
      makeChatSpec("chat-id"),
      makeChatSpec("running-chat-id"),
    ]);
    mockGetChat.mockResolvedValue({ messages: [], status: "idle" });
    mockGetPushMessages.mockResolvedValue({
      messages: [],
      pending_approvals: [],
    });
    mockUpdateChat.mockResolvedValue(makeChatSpec("chat-id"));
    delete (window as any).currentSessionId;
  });

  it("records a submitted draft session's real backend chat id", () => {
    (window as any).currentSessionId = "local-draft-session";

    sessionApi.resolveSubmittedSession("local-draft-session", "real-chat-id");

    expect(sessionApi.getRealIdForSession("local-draft-session")).toBe(
      "real-chat-id",
    );
    expect(sessionApi.getRealIdForSession("real-chat-id")).toBe("real-chat-id");
    expect((window as any).currentSessionId).toBe("real-chat-id");
  });

  it("keeps new chats in draft mode until the first message is sent", async () => {
    mockListChats.mockResolvedValueOnce([]);

    const sessions = await sessionApi.createSession({});

    expect(sessions).toEqual([]);
    expect((window as any).currentSessionId).toBeUndefined();
    expect((window as any).currentUserId).toBe("default");
    expect((window as any).currentChannel).toBe("console");
  });

  it("does not create a draft when the route already points at a real task", async () => {
    window.history.pushState({}, "", "/task/routed-chat-id");
    mockListChats.mockResolvedValue([
      {
        id: "routed-chat-id",
        name: "Existing task",
        session_id: "session-1",
        user_id: "default",
        channel: "console",
        created_at: null,
        updated_at: null,
        meta: {},
      },
    ]);

    const sessions = await sessionApi.createSession({});

    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe("routed-chat-id");
    expect((window as any).currentSessionId).toBe("session-1");
  });

  it("does not keep stale route chat ids as the active browser session", async () => {
    window.history.pushState({}, "", "/task/stale-chat-id");
    mockListChats.mockResolvedValue([]);
    mockGetChat.mockRejectedValueOnce(
      new Error('Chat not found: stale-chat-id - {"detail":"Chat not found"}'),
    );
    const onSessionRemoved = vi.fn();
    sessionApi.onSessionRemoved = onSessionRemoved;

    const sessions = await sessionApi.createSession({});

    expect(sessions).toEqual([]);
    expect((window as any).currentSessionId).toBeUndefined();
    expect(onSessionRemoved).toHaveBeenCalledWith("stale-chat-id");
  });

  it("keeps an accessible route during runtime ensureSession with an empty list", async () => {
    window.history.pushState({}, "", "/task/existing-material-chat");
    mockListChats.mockResolvedValue([]);
    mockGetChat.mockResolvedValue({ messages: [], status: "idle" });
    const removed = vi.fn();
    sessionApi.onSessionRemoved = removed;
    const sessions = await sessionApi.createSession({});
    expect(sessions.map((session) => session.id)).toContain(
      "existing-material-chat",
    );
    expect(removed).not.toHaveBeenCalled();
    expect((window as any).currentSessionId).toBe("existing-material-chat");
  });

  it("returns a draft session without generating a timestamp id", async () => {
    const session = await sessionApi.getSession(DRAFT_SESSION_ID);

    expect(session.id).toBe(DRAFT_SESSION_ID);
    expect((session as any).sessionId).toBe(DRAFT_SESSION_ID);
    expect((window as any).currentSessionId).toBeUndefined();
  });

  it("verifies route chats absent from the list before treating them as removed", async () => {
    window.history.pushState({}, "", "/task/stale-chat-id");
    const onSessionRemoved = vi.fn();
    const onSessionSelected = vi.fn();
    sessionApi.onSessionRemoved = onSessionRemoved;
    sessionApi.onSessionSelected = onSessionSelected;
    mockGetChat.mockRejectedValueOnce(
      new Error('Chat not found: stale-chat-id - {"detail":"Chat not found"}'),
    );

    const session = await sessionApi.getSession("stale-chat-id");

    expect(session.id).toBe(DRAFT_SESSION_ID);
    expect(mockGetChat).toHaveBeenCalledWith("stale-chat-id");
    expect(onSessionRemoved).toHaveBeenCalledWith("stale-chat-id");
    expect(onSessionSelected).not.toHaveBeenCalled();
  });

  it("keeps an accessible deep-linked task when the sidebar list has not caught up", async () => {
    window.history.pushState({}, "", "/task/existing-material-chat");
    mockListChats.mockResolvedValue([]);
    mockGetChat.mockResolvedValue({ messages: [], status: "idle" });
    const removed = vi.fn();
    sessionApi.onSessionRemoved = removed;
    const session = await sessionApi.getSession("existing-material-chat");
    expect(session.id).toBe("existing-material-chat");
    expect(mockGetChat).toHaveBeenCalledWith("existing-material-chat");
    expect(removed).not.toHaveBeenCalled();
  });

  it("treats inaccessible route chats as removed instead of throwing", async () => {
    window.history.pushState({}, "", "/task/stale-chat-id");
    const onSessionRemoved = vi.fn();
    const onSessionSelected = vi.fn();
    sessionApi.onSessionRemoved = onSessionRemoved;
    sessionApi.onSessionSelected = onSessionSelected;
    mockListChats.mockResolvedValue([
      {
        id: "stale-chat-id",
        name: "Stale task",
        session_id: "session-1",
        user_id: "default",
        channel: "console",
        created_at: null,
        updated_at: null,
        meta: {},
      },
    ]);
    mockGetChat.mockRejectedValueOnce(
      new Error('Chat not found: stale-chat-id - {"detail":"Chat not found"}'),
    );

    const session = await sessionApi.getSession("stale-chat-id");

    expect(session.id).toBe(DRAFT_SESSION_ID);
    expect(mockGetChat).toHaveBeenCalledWith("stale-chat-id");
    expect(onSessionRemoved).toHaveBeenCalledWith("stale-chat-id");
    expect(onSessionSelected).not.toHaveBeenCalled();
  });

  it("records a precreated backend chat as the active real session", () => {
    sessionApi.recordCreatedChat({
      id: "real-chat-id",
      name: "Real chat",
      session_id: "real-chat-id",
      user_id: "default",
      channel: "console",
      created_at: null,
      updated_at: null,
      meta: {},
    });

    expect((window as any).currentSessionId).toBe("real-chat-id");
  });

  it("clears the active browser session when reset is called", () => {
    (window as any).currentSessionId = "stale-chat-id";

    sessionApi.reset();

    expect((window as any).currentSessionId).toBeUndefined();
  });

  it("uses full access as the default for a new draft", async () => {
    expect(await sessionApi.getLocalAccessMode(DRAFT_SESSION_ID)).toBe(
      DEFAULT_LOCAL_ACCESS_MODE,
    );
  });

  it("keeps the safe ask-for-approval fallback for a legacy chat", async () => {
    mockListChats.mockResolvedValueOnce([
      makeChatSpec("legacy-chat-id", { meta: {} }),
    ]);
    await sessionApi.getSessionList();

    expect(await sessionApi.getLocalAccessMode("legacy-chat-id")).toBe(
      "ask_for_approval",
    );
  });

  it("keeps the selected local access mode on a draft", async () => {
    await sessionApi.setLocalAccessMode(DRAFT_SESSION_ID, "full_access");

    expect(await sessionApi.getLocalAccessMode(DRAFT_SESSION_ID)).toBe(
      "full_access",
    );
    expect(mockUpdateChat).not.toHaveBeenCalled();
  });

  it("persists the selected local access mode for an existing chat", async () => {
    mockListChats.mockResolvedValueOnce([
      makeChatSpec("chat-id", {
        meta: { local_access_mode: "ask_for_approval" },
      }),
    ]);
    mockUpdateChat.mockResolvedValueOnce(
      makeChatSpec("chat-id", {
        meta: { local_access_mode: "full_access" },
      }),
    );
    await sessionApi.getSessionList();

    const saved = await sessionApi.setLocalAccessMode(
      "chat-id",
      "full_access",
      "agent-1",
    );

    expect(mockUpdateChat).toHaveBeenCalledWith(
      "chat-id",
      { meta: { local_access_mode: "full_access" } },
      "agent-1",
    );
    expect(saved).toBe("full_access");
    expect(await sessionApi.getLocalAccessMode("chat-id")).toBe("full_access");
  });

  it("resolves the backend session id from the current URL chat id", async () => {
    mockListChats.mockResolvedValue([
      {
        id: "chat-uuid",
        name: "Existing task",
        session_id: "legacy-session-id",
        user_id: "default",
        channel: "console",
        created_at: null,
        updated_at: null,
        meta: {},
      },
    ]);

    const sessionId = await sessionApi.getSessionIdForChatId("chat-uuid");

    expect(sessionId).toBe("legacy-session-id");
  });

  it("falls back to the route chat id when the chat is not in the list", async () => {
    mockListChats.mockResolvedValue([]);

    const sessionId = await sessionApi.getSessionIdForChatId("chat-uuid");

    expect(sessionId).toBe("chat-uuid");
  });

  it("replaces local timestamp ids with backend ids after list refresh", async () => {
    sessionApi.resolveSubmittedSession("1717000000000", "real-chat-id");
    mockListChats.mockResolvedValue([
      {
        id: "real-chat-id",
        name: "Real chat",
        session_id: "1717000000000",
        user_id: "default",
        channel: "console",
        created_at: null,
        updated_at: null,
        meta: {},
      },
    ]);

    const sessions = await sessionApi.getSessionList();

    expect(sessions[0].id).toBe("real-chat-id");
    expect(sessionApi.getRealIdForSession("1717000000000")).toBe(
      "real-chat-id",
    );
  });

  it("leaves the in-flight response for reconnect on running reloads", async () => {
    mockListChats.mockResolvedValue([
      {
        id: "running-chat-id",
        name: "Running chat",
        session_id: "session-1",
        user_id: "default",
        channel: "console",
        created_at: null,
        updated_at: null,
        meta: {},
      },
    ]);
    mockGetChat.mockResolvedValue({
      status: "running",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [{ type: "text", text: "继续写" }],
        },
      ],
    });

    const session = await sessionApi.getSession("running-chat-id");
    const messages = session.messages || [];

    expect((session as any).generating).toBe(true);
    expect(messages).toHaveLength(1);
    expect((messages[0] as any).role).toBe("user");
    expect(mockGetPushMessages).not.toHaveBeenCalled();
  });

  it("does not render cached live text before reconnect owns the running response", async () => {
    appendLiveResponseText("running-chat-id", "第一段");
    appendLiveResponseText("running-chat-id", "第二段");
    mockGetChat.mockResolvedValue({
      status: "running",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [{ type: "text", text: "继续写" }],
        },
      ],
    });

    const session = await sessionApi.getSession("running-chat-id");
    const messages = session.messages || [];

    expect(messages).toHaveLength(1);
    expect((messages[0] as any).role).toBe("user");
  });

  it("does not consume console push messages before reconnect owns the running response", async () => {
    mockGetChat.mockResolvedValue({
      status: "running",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [{ type: "text", text: "继续写" }],
        },
      ],
    });
    mockGetPushMessages.mockResolvedValueOnce({
      messages: [{ id: "push-1", text: "后台仍在生成" }],
      pending_approvals: [],
    });

    const session = await sessionApi.getSession("running-chat-id");
    const messages = session.messages || [];

    expect(mockGetPushMessages).not.toHaveBeenCalled();
    expect(messages).toHaveLength(1);
    expect((messages[0] as any).role).toBe("user");
  });

  it("drops backend partial assistant messages so reconnect does not duplicate the current answer", async () => {
    mockGetChat.mockResolvedValue({
      status: "running",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [{ type: "text", text: "继续写" }],
        },
        {
          id: "msg-assistant",
          role: "assistant",
          type: "message",
          content: [{ type: "text", text: "已经写到一半" }],
        },
      ],
    });

    const session = await sessionApi.getSession("running-chat-id");
    const messages = session.messages || [];

    expect(messages).toHaveLength(1);
    expect((messages[0] as any).role).toBe("user");
  });

  it("hides internal skill invocation prefixes from user message display", async () => {
    mockGetChat.mockResolvedValue({
      status: "idle",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [
            {
              type: "text",
              text: "/[短剧创作工坊-20260528055448]\n\n创作一个6月1日儿童节的剧本",
            },
          ],
        },
      ],
    });

    const session = await sessionApi.getSession("chat-id");
    const messages = session.messages || [];
    const userContent = (messages[0] as any).cards[0].data.input[0].content;

    expect(userContent[0].text).toBe("创作一个6月1日儿童节的剧本");
  });

  it("hides injected bootstrap and skill scaffolding from user message display", async () => {
    mockGetChat.mockResolvedValue({
      status: "idle",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [
            {
              type: "text",
              text: [
                "# 引导模式",
                "",
                "工作目录中存在 `BOOTSTRAP.md` — 首次设置。",
                "",
                "---",
                "",
                "Use the [短剧创作工坊-20260528055448] skill in `/Users/zu/.qwenpaw/workspaces/default/skills/短剧创作工坊-20260528055448` to fulfill user's task: 创作一个6月1日儿童节的剧本",
                "",
                "# 短剧创作工坊 🎬",
                "",
                "## 技能简介",
                "",
                "这是一个专业的短剧创作全流程工具。",
              ].join("\n"),
            },
          ],
        },
      ],
    });

    const session = await sessionApi.getSession("chat-id");
    const messages = session.messages || [];
    const userContent = (messages[0] as any).cards[0].data.input[0].content;

    expect(userContent[0].text).toBe("创作一个6月1日儿童节的剧本");
  });

  it("uses the chat agent when rewriting structured history video URLs", async () => {
    const videoSource = {
      type: "url",
      url: "file:///app/working/sealed_agents/runtime_workspaces/luyu_traffic_operator/release/agent/aigc_studio/result.mp4",
    };
    mockListChats.mockResolvedValueOnce([
      makeChatSpec("chat-id", {
        meta: { agent_id: "luyu_traffic_operator" },
      }),
    ]);
    mockGetChat.mockResolvedValue({
      status: "idle",
      messages: [
        {
          id: "msg-user",
          role: "user",
          type: "message",
          content: [{ type: "video", source: videoSource }],
        },
      ],
    });

    await sessionApi.getSessionList();
    await sessionApi.getSession("chat-id");

    expect(videoSource.url).toContain("chatId=chat-id");
    expect(videoSource.url).toContain("agent_id=luyu_traffic_operator");
  });

  it("uses fresh backend status when refreshing the session list", async () => {
    const runningChat: ChatSpec = {
      id: "chat-id",
      name: "Status chat",
      session_id: "session-1",
      user_id: "default",
      channel: "console",
      created_at: null,
      updated_at: null,
      meta: {},
      status: "running",
    };

    mockListChats
      .mockResolvedValueOnce([runningChat])
      .mockResolvedValueOnce([{ ...runningChat, status: "idle" }]);

    const first = await sessionApi.getSessionList();
    const second = await sessionApi.getSessionList();

    expect((first[0] as any).generating).toBe(true);
    expect((second[0] as any).generating).toBe(false);
  });

  it("notifies when a running session becomes idle", async () => {
    const onGeneratingStatusChange = vi.fn();
    sessionApi.onGeneratingStatusChange = onGeneratingStatusChange;

    mockGetChat
      .mockResolvedValueOnce({
        status: "running",
        messages: [
          {
            id: "msg-user",
            role: "user",
            type: "message",
            content: [{ type: "text", text: "继续写" }],
          },
        ],
      })
      .mockResolvedValueOnce({
        status: "idle",
        messages: [
          {
            id: "msg-user",
            role: "user",
            type: "message",
            content: [{ type: "text", text: "继续写" }],
          },
          {
            id: "msg-assistant",
            role: "assistant",
            type: "message",
            content: [{ type: "text", text: "完成了" }],
          },
        ],
      });

    await sessionApi.getSession("chat-id");
    await sessionApi.getSession("chat-id");

    expect(onGeneratingStatusChange).toHaveBeenNthCalledWith(1, true);
    expect(onGeneratingStatusChange).toHaveBeenNthCalledWith(2, false);
  });
});
