import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useLocation, useNavigate } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import TaskPage from "./index";

import { agentsApi } from "../../api/modules/agents";
vi.mock("../../api/modules/agents", () => ({
  agentsApi: { listAgents: vi.fn() },
}));

let capturedOptions: any = null;
let currentPathname = "";

const {
  mockGetActiveModels,
  mockListProviders,
  mockCreateChat,
  mockListChats,
  mockGetApiUrl,
  mockRecordCreatedChat,
  mockResolveSubmittedSession,
  mockSetLastUserMessage,
  mockGetSession,
  mockGetChat,
  mockGetChatStatus,
  mockSetActiveSessionId,
  mockUseAgentStore,
  mockGetPlanConfig,
  mockGetTranscriptionProviderType,
  mockGetRunByChat,
  mockGetExpertTeam,
  mockChatSubmit,
  mockListAigcCards,
  mockGetAigcTask,
  mockListInteractions,
  mockSubmitInteraction,
} = vi.hoisted(() => {
  const store = vi.fn(() => ({
    selectedAgent: "default",
    selectedExpertTeam: null,
    currentExpertTeamRun: null,
    setSelectedExpertTeam: vi.fn(),
    setCurrentExpertTeamRun: vi.fn(),
    setLastChatId: vi.fn(),
    getLastChatId: vi.fn(() => undefined),
  })) as any;
  store.getState = vi.fn(() => ({ selectedExpertTeam: null }));

  return {
    mockGetActiveModels: vi.fn(),
    mockListProviders: vi.fn(),
    mockCreateChat: vi.fn(),
    mockListChats: vi.fn(),
    mockGetApiUrl: vi.fn((path: string) => `/api${path}`),
    mockRecordCreatedChat: vi.fn(),
    mockResolveSubmittedSession: vi.fn(),
    mockSetLastUserMessage: vi.fn(),
    mockGetSession: vi.fn(),
    mockGetChat: vi.fn(),
    mockGetChatStatus: vi.fn(),
    mockSetActiveSessionId: vi.fn(),
    mockUseAgentStore: store,
    mockGetPlanConfig: vi.fn(),
    mockGetTranscriptionProviderType: vi.fn(),
    mockGetRunByChat: vi.fn(),
    mockGetExpertTeam: vi.fn(),
    mockChatSubmit: vi.fn(),
    mockListAigcCards: vi.fn(),
    mockGetAigcTask: vi.fn(),
    mockListInteractions: vi.fn(),
    mockSubmitInteraction: vi.fn(),
  };
});

vi.mock("../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: {
    listCards: mockListAigcCards,
    getTask: mockGetAigcTask,
    command: vi.fn(),
    listInteractions: mockListInteractions,
    submitInteraction: mockSubmitInteraction,
  },
}));

vi.mock("@agentscope-ai/chat", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  type MockRuntimeProps = { options?: unknown };
  type MockRuntimeHandle = {
    input: { submit: typeof mockChatSubmit };
    messages: { getMessages: () => unknown[] };
  };
  const MockAgentScopeRuntimeWebUI = React.forwardRef<
    MockRuntimeHandle,
    MockRuntimeProps
  >((props, ref) => {
    capturedOptions = props.options;
    React.useImperativeHandle(ref, () => ({
      input: { submit: mockChatSubmit },
      messages: { getMessages: vi.fn(() => []) },
    }));
    const responseCard = (props.options as any)?.cards
      ?.AgentScopeRuntimeResponseCard;
    return (
      <>
        <div data-testid="task-chat-ui" />
        <article data-testid="assistant-response">
          {typeof responseCard === "function"
            ? responseCard({
                data: {
                  id: "response-1",
                  status: "completed",
                  output: [
                    {
                      id: "message-1",
                      type: "message",
                      status: "completed",
                      content: [{ type: "text", text: "请填写以下信息。" }],
                    },
                  ],
                },
                // The chat library renders messages in descending DOM order,
                // so the newest response is not marked as `isLast`.
                isLast: false,
              })
            : null}
        </article>
      </>
    );
  });
  return {
    AgentScopeRuntimeWebUI: MockAgentScopeRuntimeWebUI,
    Markdown: ({ content }: { content: string }) => <div>{content}</div>,
    useChatAnywhereSessionsState: vi.fn(() => ({
      currentSessionId: undefined,
      sessions: [],
      setCurrentSessionId: vi.fn(),
      setSessions: vi.fn(),
    })),
    useChatAnywhereInput: vi.fn(() => ({
      setLoading: vi.fn(),
      getLoading: vi.fn(),
    })),
  };
});

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: mockUseAgentStore,
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }),
}));

vi.mock("../../contexts/ApprovalContext", () => ({
  useApprovalContext: () => ({
    approvals: [],
    setApprovals: vi.fn(),
  }),
}));

vi.mock("../../plugins/PluginContext", () => ({
  usePlugins: () => ({
    plugins: [],
    registerPlugin: vi.fn(),
    toolRenderConfig: {},
  }),
}));

vi.mock("../../api/modules/provider", () => ({
  providerApi: {
    listProviders: mockListProviders,
    getActiveModels: mockGetActiveModels,
  },
}));

vi.mock("../../api/modules/chat", () => ({
  chatApi: {
    createChat: mockCreateChat,
    listChats: mockListChats,
    updateChat: vi.fn(() => Promise.resolve({})),
    getChat: mockGetChat,
    getChatStatus: mockGetChatStatus,
    uploadFile: vi.fn(),
    filePreviewUrl: vi.fn((file: string) => `/preview/${file}`),
    stopChat: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("../../api/modules/expertTeams", () => ({
  expertTeamsApi: {
    getRunByChat: mockGetRunByChat,
    getExpertTeam: mockGetExpertTeam,
  },
}));

vi.mock("../../api/modules/agent", () => ({
  agentApi: {
    getTranscriptionProviderType: mockGetTranscriptionProviderType,
  },
}));

vi.mock("../../api/modules/commands", () => ({
  commandsApi: {
    sendApprovalCommand: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("../../api/modules/plan", () => ({
  planApi: {
    getPlanConfig: mockGetPlanConfig,
  },
}));

vi.mock("../../api/config", () => ({
  getApiUrl: mockGetApiUrl,
  getApiToken: vi.fn(() => ""),
}));

vi.mock("../../api/authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("../Chat/sessionApi", () => ({
  default: {
    preferredChatId: null,
    onSessionIdResolved: null,
    onSessionRemoved: null,
    onSessionSelected: null,
    onSessionCreated: null,
    onSessionLoadStart: null,
    onSessionLoadEnd: null,
    onGeneratingStatusChange: null,
    getSessionIdForChatId: vi.fn((chatId: string) => Promise.resolve(chatId)),
    getRealIdForSession: vi.fn(() => null),
    setLastUserMessage: mockSetLastUserMessage,
    recordCreatedChat: mockRecordCreatedChat,
    resolveSubmittedSession: mockResolveSubmittedSession,
    getSession: mockGetSession,
    reset: vi.fn(),
  },
  isDraftSessionId: (sessionId?: string | null) =>
    !sessionId || sessionId === "draft-session",
  DRAFT_SESSION_ID: "draft-session",
}));

vi.mock("../Chat/components/ChatSessionInitializer", () => ({
  default: () => null,
}));

vi.mock("../../contexts/RuntimeEventContext", () => ({
  useRuntimeEvents: () => ({
    activeSessionId: null,
    setActiveSessionId: mockSetActiveSessionId,
    connected: true,
    fallbackPolling: false,
    lastEventId: null,
    events: [],
    clearEvents: vi.fn(),
  }),
}));

vi.mock("../../components/WorkbenchInput", () => ({
  default: ({
    disabled,
    topAccessory,
  }: {
    disabled?: boolean;
    topAccessory?: React.ReactNode;
  }) => (
    <div data-testid="workbench-input" data-disabled={disabled || undefined}>
      {topAccessory}
    </div>
  ),
}));

vi.mock("../Chat/components/ChatActionGroup", () => ({
  default: () => <div data-testid="action-group" />,
}));

vi.mock("../Chat/components/ChatHeaderTitle", () => ({
  default: () => <div data-testid="header-title" />,
}));

vi.mock("../../components/ApprovalCard/ApprovalDialog", () => ({
  ApprovalDialog: () => <div data-testid="approval-dialog" />,
}));

vi.mock("../Chat/components/ArtifactPanel", () => ({
  default: () => <div data-testid="artifact-panel" />,
}));

vi.mock("../Chat/components/RunningSessionNotice", () => ({
  default: () => <div data-testid="running-notice" />,
}));

vi.mock("../Chat/components/ExpertTeamStatusStrip", () => ({
  default: () => <div data-testid="expert-team-status" />,
}));

vi.mock("../Chat/components/PreparingOverlay", () => ({
  default: ({ mode }: { mode?: string }) => (
    <div data-testid="preparing-overlay" data-mode={mode} />
  ),
}));

vi.mock("../Chat/components/TaskArtifactCard", () => ({
  TaskArtifactCard: () => <div data-testid="task-artifact-card" />,
}));

vi.mock("../Chat/components/WhisperSpeechButton", () => ({
  default: () => <button type="button" data-testid="whisper-button" />,
}));

vi.mock("../Chat/utils/artifactCardScanScheduler", () => ({
  scheduleArtifactCardScans: vi.fn(() => () => {}),
}));

vi.mock("../../utils/expertTeamSelection", () => ({
  loadExpertTeamSelectionForChat: vi.fn(() => null),
  saveExpertTeamSelectionForChat: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();
  currentPathname = location.pathname;
  return null;
}

function TaskRouteSwitchProbe() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/task/replacement-task")}>
      switch task route
    </button>
  );
}

function buildChatResponse(chatId: string): Response {
  return new Response("data: {}\n\n", {
    status: 200,
    headers: { "X-QwenPaw-Chat-Id": chatId },
  });
}

describe("TaskPage", () => {
  const originalVisibilityState = Object.getOwnPropertyDescriptor(
    Document.prototype,
    "visibilityState",
  );

  function setDocumentVisibilityState(state: DocumentVisibilityState) {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => state,
    });
  }

  it("passes the summoned super expert identity to task response cards", async () => {
    const initialStore = mockUseAgentStore();
    mockUseAgentStore.mockReturnValue({
      ...initialStore,
      selectedAgent: "luyu_traffic_operator",
    });
    vi.mocked(agentsApi.listAgents).mockResolvedValue({
      agents: [
        {
          id: "luyu_traffic_operator",
          name: "陆羽",
          description: "",
          enabled: true,
          agent_type: "sealed",
          avatar: "data:image/png;base64,portrait",
          open_api_enabled: true,
        },
      ],
    });
    try {
      renderWithProviders(<TaskPage />, {
        initialEntries: ["/task/existing-chat"],
      });
      await waitFor(() => expect(capturedOptions?.welcome.nick).toBe("陆羽"));
      const card = capturedOptions.cards.AgentScopeRuntimeResponseCard({
        data: { status: "completed", output: [] },
      });
      expect(card.props.identity).toEqual({
        name: "陆羽",
        avatar: "data:image/png;base64,portrait",
        isSuperExpert: true,
      });
    } finally {
      mockUseAgentStore.mockReturnValue(initialStore);
    }
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentsApi.listAgents).mockResolvedValue({ agents: [] });
    vi.useRealTimers();
    capturedOptions = null;
    mockListAigcCards.mockResolvedValue({ cards: [] });
    mockListInteractions.mockResolvedValue({ interactions: [] });
    currentPathname = "";
    sessionStorage.clear();
    setDocumentVisibilityState("visible");
    delete (window as any).currentSessionId;
    delete (window as any).currentUserId;
    delete (window as any).currentChannel;
    mockListProviders.mockResolvedValue([]);
    mockGetActiveModels.mockResolvedValue({
      active_llm: { provider_id: "openai", model: "gpt-4" },
    });
    mockCreateChat.mockResolvedValue({
      id: "created-chat-id",
      name: "hello",
      session_id: "created-chat-id",
      user_id: "42",
      channel: "console",
      created_at: null,
      updated_at: null,
      meta: {},
    });
    mockListChats.mockResolvedValue([]);
    mockGetChat.mockResolvedValue({ messages: [], status: "idle" });
    mockGetChatStatus.mockResolvedValue({
      id: "created-chat-id",
      status: "idle",
      task_status: "completed",
      updated_at: null,
      message_count: 1,
    });
    mockGetSession.mockResolvedValue({ messages: [] });
    mockGetPlanConfig.mockResolvedValue({ enabled: false });
    mockGetTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "disabled",
    });
    mockGetRunByChat.mockResolvedValue(null);
    mockGetExpertTeam.mockResolvedValue(null);
    global.fetch = vi
      .fn()
      .mockResolvedValue(buildChatResponse("created-chat-id"));
  });

  afterEach(() => {
    vi.useRealTimers();
    if (originalVisibilityState) {
      Object.defineProperty(
        Document.prototype,
        "visibilityState",
        originalVisibilityState,
      );
      delete (document as any).visibilityState;
    }
    vi.clearAllMocks();
    vi.mocked(agentsApi.listAgents).mockResolvedValue({ agents: [] });
    sessionStorage.clear();
  });

  it("restores a clickable AIGC card on /task after reopening without SSE events", async () => {
    const binding = {
      installation_id: "install-1",
      conversation_id: "demo-chat",
      agent_task_id: "task-1",
      content_revision: 1,
      material_task_id: "material-1",
      canvas_id: "canvas-1",
      node_id: "video-1",
      workflow_id: "workflow-1",
    };
    mockListAigcCards.mockResolvedValue({
      cards: [
        {
          material_task_id: "material-1",
          title: "生成主题图片和视频",
          status: "IN_PROGRESS",
          binding,
          href: "/aigc-studio?task=material-1",
          instruction: "先生成图片，再生成视频",
        },
      ],
    });
    mockGetAigcTask.mockResolvedValue({ binding, status: "IN_PROGRESS" });
    const view = renderWithProviders(<TaskPage />, {
      initialEntries: ["/task/demo-chat"],
    });
    expect(await screen.findByText("生成主题图片和视频")).toBeVisible();
    expect(screen.getByRole("button", { name: "继续制作" })).toHaveAttribute(
      "data-deep-link",
      "/aigc-studio?task=material-1",
    );
    view.unmount();
    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/demo-chat"] },
    );
    expect(await screen.findByText("生成主题图片和视频")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "继续制作" }));
    await waitFor(() => expect(currentPathname).toBe("/aigc-studio"));
  });

  it("restores a pending question card and blocks text input on /task", async () => {
    mockListInteractions.mockResolvedValue({
      interactions: [
        {
          interaction_id: "interaction-question-1",
          binding: {
            installation_id: "install-1",
            conversation_id: "demo-chat",
            agent_task_id: "interaction-task-1",
          },
          task_key: "business-foundation",
          interaction_revision: 1,
          component_type: "question_form",
          input_policy: "card_only",
          card: {
            title: "你的业务基本情况",
            description: "请逐项填写",
            items: [
              {
                id: "business-description",
                question: "你现在做什么业务？",
                description: null,
                placeholder: "请输入业务信息",
                required: true,
                max_length: 1000,
              },
              {
                id: "product-or-service",
                question: "具体提供什么产品或服务？",
                description: null,
                placeholder: "请输入产品或服务",
                required: true,
                max_length: 1000,
              },
            ],
          },
          status: "PENDING",
          version: 1,
          transitions: [],
          answer: null,
          expires_at: null,
          created_at: "2026-09-17T06:27:24.586093Z",
          updated_at: "2026-09-17T06:27:24.586093Z",
        },
      ],
    });

    renderWithProviders(<TaskPage />, {
      initialEntries: ["/task/demo-chat"],
    });

    expect(
      screen.queryByRole("heading", { name: "你的业务基本情况" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("textbox", { name: "你现在做什么业务？" }),
    ).toBeVisible();
    expect(
      within(screen.getByTestId("assistant-response")).getByRole("region", {
        name: "基础交互",
      }),
    ).toBeVisible();
    expect(screen.getAllByTestId("question-item")).toHaveLength(2);
    expect(mockListInteractions).toHaveBeenCalledWith("demo-chat");
    await waitFor(() =>
      expect(screen.getByTestId("workbench-input")).toHaveAttribute(
        "data-disabled",
        "true",
      ),
    );
  });

  it("sends the server-resolved card output through the ordinary chat submitter", async () => {
    const pending = {
      interaction_id: "interaction-choice-1",
      binding: {
        installation_id: "install-1",
        conversation_id: "demo-chat",
        agent_task_id: "interaction-task-1",
      },
      task_key: "goal",
      interaction_revision: 1,
      component_type: "single_select",
      input_policy: "card_only",
      card: {
        title: "选择目标",
        description: null,
        options: [
          {
            id: "growth",
            text: "扩大增长",
            description: null,
            recommended: true,
            default_selected: false,
          },
        ],
        supplement: {
          enabled: false,
          label: "补充信息",
          placeholder: "",
          required: false,
          max_length: 2000,
        },
        layout: "auto",
      },
      status: "PENDING",
      version: 1,
      transitions: [],
      answer: null,
      expires_at: null,
      created_at: "2026-09-17T06:27:24.586093Z",
      updated_at: "2026-09-17T06:27:24.586093Z",
    };
    mockListInteractions.mockResolvedValue({ interactions: [pending] });
    mockSubmitInteraction.mockResolvedValue({
      interaction: {
        ...pending,
        status: "SUBMITTED",
        version: 2,
        answer: {
          selected: [{ id: "growth", text: "扩大增长" }],
          supplement: null,
        },
      },
      user_input: "扩大增长",
    });

    renderWithProviders(<TaskPage />, {
      initialEntries: ["/task/demo-chat"],
    });

    fireEvent.click(await screen.findByRole("radio", { name: /扩大增长/ }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));

    await waitFor(() =>
      expect(mockChatSubmit).toHaveBeenCalledWith({ query: "扩大增长" }),
    );
    expect(mockChatSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not open the previous chat's material when a pending click finishes after switching", async () => {
    let finish: (value: unknown) => void = () => {};
    mockGetAigcTask.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    mockListAigcCards.mockImplementation((cid: string) =>
      Promise.resolve({
        cards:
          cid === "demo-chat"
            ? [
                {
                  material_task_id: "material-1",
                  title: "旧会话素材",
                  status: "IN_PROGRESS",
                  binding: { installation_id: "install-1" },
                  instruction: "",
                },
              ]
            : [],
      }),
    );
    renderWithProviders(
      <>
        <LocationProbe />
        <TaskRouteSwitchProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/demo-chat"] },
    );
    fireEvent.click(await screen.findByRole("button", { name: "继续制作" }));
    fireEvent.click(screen.getByRole("button", { name: "switch task route" }));
    await waitFor(() => expect(currentPathname).toBe("/task/replacement-task"));
    await act(async () => {
      finish({ status: "IN_PROGRESS", binding: {} });
    });
    expect(currentPathname).toBe("/task/replacement-task");
    expect(screen.queryByText("旧会话素材")).not.toBeInTheDocument();
  });

  it("does not query expert-team runs for route chats outside the current user's list", async () => {
    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/stale-chat-id"] },
    );

    await screen.findByTestId("task-chat-ui");
    await waitFor(() => expect(mockListChats).toHaveBeenCalled());

    expect(mockGetRunByChat).not.toHaveBeenCalled();
  });

  it("continues a precreated task with the backend-confirmed user and chat id", async () => {
    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task"] },
    );
    await screen.findByTestId("task-chat-ui");

    await act(async () => {
      await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
    });

    await waitFor(() => expect(currentPathname).toBe("/task/created-chat-id"));
    expect(mockRecordCreatedChat).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "created-chat-id",
        user_id: "42",
      }),
    );
    expect(mockResolveSubmittedSession).toHaveBeenCalledWith(
      "created-chat-id",
      "created-chat-id",
    );

    const [, fetchOptions] = (fetch as any).mock.calls[0];
    const body = JSON.parse(fetchOptions.body);
    expect(body.session_id).toBe("created-chat-id");
    expect(body.user_id).toBe("42");
  });

  it("waits for the chat request to start before navigating to a new task", async () => {
    let resolveFetch: (response: Response) => void = () => {};
    global.fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task"] },
    );
    await screen.findByTestId("task-chat-ui");

    let requestPromise: Promise<Response>;
    act(() => {
      requestPromise = capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: new AbortController().signal,
      });
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(currentPathname).toBe("/task");

    await act(async () => {
      resolveFetch(buildChatResponse("created-chat-id"));
      await requestPromise!;
    });

    await waitFor(() => expect(currentPathname).toBe("/task/created-chat-id"));
  });

  it("stays on the draft route when the backend rejects a new task", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Console unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task"] },
    );
    await screen.findByTestId("task-chat-ui");

    let response: Response;
    await act(async () => {
      response = await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
    });

    expect(response!.status).toBe(503);
    expect(currentPathname).toBe("/task");
    expect(mockResolveSubmittedSession).not.toHaveBeenCalled();
  });

  it("registers the opened task as the active runtime event session", async () => {
    const view = renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/task-123"] },
    );

    await screen.findByTestId("task-chat-ui");

    expect(mockSetActiveSessionId).toHaveBeenCalledWith("task-123");

    view.unmount();

    expect(mockSetActiveSessionId).toHaveBeenCalledWith(null);
  });

  it("keeps loading feedback visible until the selected task history settles", async () => {
    renderWithProviders(
      <>
        <LocationProbe />
        <TaskRouteSwitchProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/stale-task"] },
    );

    await screen.findByTestId("preparing-overlay");
    fireEvent.click(screen.getByRole("button", { name: "switch task route" }));

    expect(await screen.findByTestId("preparing-overlay")).toHaveAttribute(
      "data-mode",
      "conversation",
    );

    await act(async () => {
      (await import("../Chat/sessionApi")).default.onSessionLoadEnd?.(
        "replacement-task",
        null,
      );
    });

    await waitFor(() =>
      expect(screen.queryByTestId("preparing-overlay")).toBeNull(),
    );
  });

  it("resumes a persisted Workbench intent for an empty precreated task after refresh", async () => {
    sessionStorage.setItem(
      "qwenpaw_pending_task_intent_recovered-task",
      JSON.stringify({
        prompt: "继续生成这份材料",
        agentId: "default",
        expertTeam: null,
      }),
    );
    mockGetChatStatus.mockResolvedValueOnce({
      id: "recovered-task",
      status: "idle",
      task_status: "pending",
      updated_at: null,
      message_count: 0,
    });

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/recovered-task"] },
    );

    await screen.findByTestId("task-chat-ui");

    await waitFor(() => {
      expect(mockGetChatStatus).toHaveBeenCalledWith(
        "recovered-task",
        "default",
      );
    });

    await act(async () => {
      (await import("../Chat/sessionApi")).default.onSessionSelected?.(
        "recovered-task",
        null,
      );
    });

    await waitFor(() => {
      expect(mockChatSubmit).toHaveBeenCalledWith({
        query: "继续生成这份材料",
      });
    });
  });

  it("submits a restored intent when the task session was already selected", async () => {
    Object.assign(window, { currentSessionId: "already-selected-task" });
    sessionStorage.setItem(
      "qwenpaw_pending_task_intent_already-selected-task",
      JSON.stringify({
        prompt: "继续生成已选中的任务",
        agentId: "default",
      }),
    );
    mockGetChatStatus.mockResolvedValueOnce({
      id: "already-selected-task",
      status: "idle",
      task_status: "pending",
      updated_at: null,
      message_count: 0,
    });

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/already-selected-task"] },
    );

    await screen.findByTestId("task-chat-ui");

    await waitFor(() => {
      expect(mockChatSubmit).toHaveBeenCalledWith({
        query: "继续生成已选中的任务",
      });
    });
  });

  it("refreshes a completed running task with the lightweight status endpoint", async () => {
    mockGetChatStatus.mockResolvedValueOnce({
      id: "running-task",
      status: "idle",
      task_status: "completed",
      updated_at: null,
      message_count: 2,
    });

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/running-task"] },
    );

    await screen.findByTestId("task-chat-ui");

    await act(async () => {
      (await import("../Chat/sessionApi")).default.onGeneratingStatusChange?.(
        true,
      );
    });

    await waitFor(() => {
      expect(mockGetChatStatus).toHaveBeenCalledWith(
        "running-task",
        "default",
        expect.any(AbortSignal),
      );
    });
    expect(mockGetChat).not.toHaveBeenCalledWith("running-task", "default");
    expect(mockGetSession).toHaveBeenCalledWith("running-task");
  });

  it("checks a running task as soon as the page becomes visible again", async () => {
    setDocumentVisibilityState("hidden");
    mockGetChatStatus.mockResolvedValueOnce({
      id: "sleeping-task",
      status: "idle",
      task_status: "completed",
      updated_at: null,
      message_count: 2,
    });

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/sleeping-task"] },
    );

    await screen.findByTestId("task-chat-ui");

    await act(async () => {
      (await import("../Chat/sessionApi")).default.onGeneratingStatusChange?.(
        true,
      );
    });

    expect(mockGetChatStatus).not.toHaveBeenCalledWith(
      "sleeping-task",
      "default",
      expect.any(AbortSignal),
    );

    setDocumentVisibilityState("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });

    expect(mockGetChatStatus).toHaveBeenCalledWith(
      "sleeping-task",
      "default",
      expect.any(AbortSignal),
    );
    expect(mockGetSession).toHaveBeenCalledWith("sleeping-task");
  });

  it("aborts a stuck status check and reconciles again after page restore", async () => {
    let firstSignal: AbortSignal | undefined;
    mockGetChatStatus
      .mockImplementationOnce((_chatId, _agentId, signal) => {
        firstSignal = signal;
        return new Promise(() => {});
      })
      .mockResolvedValueOnce({
        id: "stuck-task",
        status: "idle",
        task_status: "completed",
        updated_at: null,
        message_count: 2,
      });

    renderWithProviders(
      <>
        <LocationProbe />
        <TaskPage />
      </>,
      { initialEntries: ["/task/stuck-task"] },
    );

    await screen.findByTestId("task-chat-ui");

    await act(async () => {
      (await import("../Chat/sessionApi")).default.onGeneratingStatusChange?.(
        true,
      );
    });

    await waitFor(() => {
      expect(mockGetChatStatus).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      window.dispatchEvent(new PageTransitionEvent("pageshow"));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(mockGetChatStatus).toHaveBeenCalledTimes(2);
    });
    expect(firstSignal?.aborted).toBe(true);
    expect(mockGetSession).toHaveBeenCalledWith("stuck-task");
  });
});
