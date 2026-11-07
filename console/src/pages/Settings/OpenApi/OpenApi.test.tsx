import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OpenApiPage from "./index";

const {
  mockOpenApiApi,
  mockAgentsApi,
  mockExpertTeamsApi,
  mockAdminUsersApi,
  mockMessage,
} = vi.hoisted(() => {
  const message = {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  };

  return {
    mockOpenApiApi: {
      listPublications: vi.fn(),
      createPublication: vi.fn(),
      updatePublicationStatus: vi.fn(),
      updatePublicationBoundUser: vi.fn(),
      deletePublication: vi.fn(),
      listApps: vi.fn(),
      createApp: vi.fn(),
      listKeys: vi.fn(),
      createKey: vi.fn(),
      revokeKey: vi.fn(),
      listInvocations: vi.fn(),
      getFallbackModel: vi.fn(),
      listFallbackModelOptions: vi.fn(),
      updateFallbackModel: vi.fn(),
    },
    mockAgentsApi: {
      listAgents: vi.fn(),
    },
    mockExpertTeamsApi: {
      listAdminExpertTeams: vi.fn(),
    },
    mockAdminUsersApi: {
      listUsers: vi.fn(),
    },
    mockMessage: message,
  };
});

vi.mock("../../../api", () => ({
  openApiApi: mockOpenApiApi,
  agentsApi: mockAgentsApi,
  expertTeamsApi: mockExpertTeamsApi,
  adminUsersApi: mockAdminUsersApi,
  DEFAULT_OPEN_API_SCOPES: ["messages:create"],
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({ current }: { current: string }) => <h1>{current}</h1>,
}));

vi.mock("@/components/AgentExperienceLibrary", () => ({
  AgentExperienceLibrary: () => (
    <div data-testid="shared-agent-experience-library">共享经验库组件</div>
  ),
}));

describe("OpenApiPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenApiApi.listPublications.mockResolvedValue([
      {
        id: "pub-1",
        public_id: "support_agent",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-1",
        title: "客服专家",
        name: "客服专家",
        description: "对外客服入口",
        status: "enabled",
        scopes: ["messages:create"],
        allowed_scopes: ["messages:create"],
        created_at: "2026-07-02T09:00:00Z",
        updated_at: "2026-07-02T09:00:00Z",
      },
    ]);
    mockOpenApiApi.listApps.mockResolvedValue([
      {
        id: "app-1",
        name: "CRM",
        status: "enabled",
        created_at: "2026-07-02T09:00:00Z",
      },
    ]);
    mockAgentsApi.listAgents.mockResolvedValue({
      agents: [
        {
          id: "agent-1",
          name: "客服专家",
          description: "Support",
          workspace_dir: "agents/support",
          enabled: true,
        },
      ],
    });
    mockExpertTeamsApi.listAdminExpertTeams.mockResolvedValue([]);
    mockAdminUsersApi.listUsers.mockResolvedValue([
      {
        id: 7,
        username: "knowledge-owner",
        role: "user",
        created_at: "2026-07-02T08:00:00Z",
      },
      {
        id: 9,
        username: "new-owner",
        role: "user",
        created_at: "2026-07-03T08:00:00Z",
      },
    ]);
    mockOpenApiApi.listKeys.mockResolvedValue([]);
    mockOpenApiApi.listInvocations.mockResolvedValue([]);
    mockOpenApiApi.getFallbackModel.mockResolvedValue({
      enabled: false,
      provider_id: "",
      model: "",
      json_object: true,
    });
    mockOpenApiApi.listFallbackModelOptions.mockResolvedValue([
      {
        provider_id: "volcengine-cn",
        provider_name: "Volcano Engine",
        model: "deepseek-v4-flash-ga-260731",
        model_name: "DeepSeek V4 Flash",
      },
    ]);
    mockOpenApiApi.updateFallbackModel.mockResolvedValue({
      enabled: true,
      provider_id: "volcengine-cn",
      model: "deepseek-v4-flash-ga-260731",
      json_object: true,
    });
    mockOpenApiApi.deletePublication.mockResolvedValue({
      deleted: true,
      id: "pub-disabled",
    });
    mockOpenApiApi.createKey.mockResolvedValue({
      secret: "qp_live_secret_once",
      key: {
        id: "key-1",
        app_id: "app-1",
        publication_id: "pub-1",
        name: "默认密钥",
        key_prefix: "qp_live",
        key_suffix: "once",
        scopes: ["messages:create"],
        status: "active",
        created_at: "2026-07-02T09:05:00Z",
      },
    });
  });

  it("configures one shared fallback model for OpenAPI agents", async () => {
    const user = userEvent.setup();
    render(<OpenApiPage />);

    await user.click(await screen.findByRole("tab", { name: "备用大模型" }));
    await user.click(screen.getByRole("switch", { name: "启用备用大模型" }));
    await user.click(screen.getByRole("combobox"));
    await user.click(
      await screen.findByText("Volcano Engine / DeepSeek V4 Flash"),
    );
    await user.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      expect(mockOpenApiApi.updateFallbackModel).toHaveBeenCalledWith({
        enabled: true,
        provider_id: "volcengine-cn",
        model: "deepseek-v4-flash-ga-260731",
        json_object: true,
      });
    });
  });

  it("keeps save disabled when no DeepSeek fallback is available", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.listFallbackModelOptions.mockResolvedValue([]);
    render(<OpenApiPage />);

    await user.click(await screen.findByRole("tab", { name: "备用大模型" }));
    await user.click(screen.getByRole("switch", { name: "启用备用大模型" }));

    expect(
      await screen.findByText(
        "暂无可用的 DeepSeek 模型，请先前往“模型”页面配置并启用。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeDisabled();
  });

  it("filters invocation routes and keeps the table human-readable", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.listInvocations.mockResolvedValue([
      {
        id: "inv-primary-uuid",
        app_id: "app-1",
        publication_id: "pub-1",
        api_key_id: "key-1",
        target_type: "agent",
        target_id: "agent-1",
        external_user_id: "张三",
        external_session_id: "opaque-session-primary",
        status: "succeeded",
        status_code: 200,
        latency_ms: 1200,
        token_summary: {
          model_route: "primary",
          primary_model: "deepseek/deepseek-chat",
        },
      },
      {
        id: "inv-fallback-uuid",
        app_id: "app-1",
        publication_id: "pub-1",
        api_key_id: "key-1",
        target_type: "agent",
        target_id: "agent-1",
        external_user_id: "李四",
        external_session_id: "opaque-session-fallback",
        status: "succeeded",
        status_code: 200,
        latency_ms: 2200,
        token_summary: {
          model_route: "fallback",
          primary_error: "HTTP 500",
          fallback_model: "volcengine-cn/deepseek-v4-flash-ga-260731",
        },
      },
    ]);
    render(<OpenApiPage />);

    await user.click(await screen.findByRole("tab", { name: "调用记录" }));
    const panel = await screen.findByRole("tabpanel", { name: "调用记录" });

    expect(within(panel).getAllByText("客户").length).toBeGreaterThan(0);
    expect(within(panel).queryByText("外部用户")).not.toBeInTheDocument();
    expect(within(panel).queryByText("会话")).not.toBeInTheDocument();
    expect(
      within(panel).queryByText("inv-primary-uuid"),
    ).not.toBeInTheDocument();
    expect(
      within(panel).queryByText("opaque-session-primary"),
    ).not.toBeInTheDocument();
    expect(within(panel).getByText("张三")).toBeInTheDocument();
    expect(within(panel).getByText("李四")).toBeInTheDocument();

    await user.click(
      within(panel).getByRole("radio", { name: "备用模型" }).closest("label")!,
    );
    expect(within(panel).queryByText("张三")).not.toBeInTheDocument();
    expect(within(panel).getByText("李四")).toBeInTheDocument();
    expect(within(panel).getByText("默认失败：HTTP 500")).toBeInTheDocument();

    await user.click(
      within(panel).getByRole("radio", { name: "默认模型" }).closest("label")!,
    );
    expect(within(panel).getByText("张三")).toBeInTheDocument();
    expect(within(panel).queryByText("李四")).not.toBeInTheDocument();
  });

  it("loads publications and shows a one-time secret after creating a key", async () => {
    const user = userEvent.setup();

    render(<OpenApiPage />);

    expect((await screen.findAllByText("客服专家")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("tab", { name: "应用与密钥" }));
    expect((await screen.findAllByText("CRM")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /创建 API Key/ }));
    const keyButtons = screen.getAllByRole("button", {
      name: "创建 API Key",
    });
    await user.click(keyButtons[keyButtons.length - 1]);

    await waitFor(() => {
      expect(mockOpenApiApi.createKey).toHaveBeenCalledWith(
        expect.objectContaining({
          publication_id: "pub-1",
          app_id: "app-1",
          scopes: ["messages:create"],
        }),
      );
    });
    expect(await screen.findByText("qp_live_secret_once")).toBeInTheDocument();
  });

  it("sends an IP allowlist when creating an external app", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.createApp.mockResolvedValue({
      id: "app-2",
      name: "Mini Program",
      status: "enabled",
      ip_allowlist: ["127.0.0.1", "10.0.0.8"],
    });

    render(<OpenApiPage />);

    await screen.findByText("Open API");
    await user.click(screen.getByRole("tab", { name: "应用与密钥" }));
    await user.click(screen.getByRole("button", { name: "创建外部应用" }));
    await user.type(
      screen.getByPlaceholderText("CRM / 小程序 / 内部系统"),
      "Mini Program",
    );
    await user.type(
      screen.getByPlaceholderText(
        "留空表示不限 IP；多个 IP 可用逗号或换行分隔",
      ),
      "127.0.0.1, 10.0.0.8",
    );
    const createButtons = screen.getAllByRole("button", {
      name: "创建外部应用",
    });
    await user.click(createButtons[createButtons.length - 1]);

    await waitFor(() => {
      expect(mockOpenApiApi.createApp).toHaveBeenCalledWith({
        name: "Mini Program",
        ip_allowlist: ["127.0.0.1", "10.0.0.8"],
      });
    });
  });

  it("does not allow creating a key for a disabled publication", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.listPublications.mockResolvedValue([
      {
        id: "pub-disabled",
        public_id: "support_agent",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-disabled",
        name: "客服专家",
        status: "disabled",
        allowed_scopes: ["messages:create"],
      },
    ]);

    render(<OpenApiPage />);

    await user.click(await screen.findByRole("tab", { name: "应用与密钥" }));
    const button = await screen.findByRole("button", { name: /创建 API Key/ });

    expect(button).toBeDisabled();
    expect(mockOpenApiApi.createKey).not.toHaveBeenCalled();
  });

  it("omits disabled publications from application and key selectors", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.listPublications.mockResolvedValue([
      {
        id: "pub-enabled",
        public_id: "support_agent",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-enabled",
        name: "在线客服接口",
        status: "enabled",
        allowed_scopes: ["messages:create"],
      },
      {
        id: "pub-disabled",
        public_id: "legacy_support",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-disabled",
        name: "旧客服接口",
        status: "disabled",
        allowed_scopes: ["messages:create"],
      },
    ]);

    render(<OpenApiPage />);

    await user.click(await screen.findByRole("tab", { name: "应用与密钥" }));
    const credentialsPanel = await screen.findByRole("tabpanel", {
      name: "应用与密钥",
    });
    await user.click(within(credentialsPanel).getByRole("combobox"));

    expect((await screen.findAllByText(/在线客服接口/)).length).toBeGreaterThan(
      0,
    );
    expect(screen.queryByText(/legacy_support/)).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /创建 API Key/ }));
    const comboboxes = screen.getAllByRole("combobox");
    await user.click(comboboxes[comboboxes.length - 3]);

    expect((await screen.findAllByText(/在线客服接口/)).length).toBeGreaterThan(
      0,
    );
    expect(screen.queryByText(/legacy_support/)).not.toBeInTheDocument();
  });

  it("hides disabled publications by default and reveals them on request", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.listPublications.mockResolvedValue([
      {
        id: "pub-enabled",
        public_id: "support_agent",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-enabled",
        name: "在线客服接口",
        status: "enabled",
        allowed_scopes: ["messages:create"],
      },
      {
        id: "pub-disabled",
        public_id: "legacy_support",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-disabled",
        name: "旧客服接口",
        status: "disabled",
        allowed_scopes: ["messages:create"],
      },
    ]);

    render(<OpenApiPage />);

    expect(await screen.findByText("在线客服接口")).toBeInTheDocument();
    expect(screen.queryByText("旧客服接口")).not.toBeInTheDocument();

    await user.click(screen.getByRole("switch", { name: "仅显示启用" }));

    expect(await screen.findByText("旧客服接口")).toBeInTheDocument();
  });

  it("edits the publication owner used by future OpenAPI calls", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.updatePublicationBoundUser.mockResolvedValue({
      id: "pub-1",
      public_id: "support_agent",
      target_type: "agent",
      target_id: "agent-1",
      bound_user_id: "9",
      knowledge_base_id: "openapi-pub-1",
      name: "客服专家",
      status: "enabled",
      allowed_scopes: ["messages:create"],
    });

    render(<OpenApiPage />);

    expect((await screen.findAllByText("归属用户")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "修改归属用户" }));
    const notice = await screen.findByText(
      "修改仅影响后续 OpenAPI 调用，历史调用和计费记录不会改变。",
    );
    const dialog = notice.closest<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    await user.click(within(dialog!).getByRole("combobox"));
    await user.click(await screen.findByText(/new-owner/));
    await user.click(within(dialog!).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      expect(mockOpenApiApi.updatePublicationBoundUser).toHaveBeenCalledWith(
        "pub-1",
        9,
      );
    });
    expect(await screen.findByText("new-owner")).toBeInTheDocument();
  });

  it("deletes a disabled publication after confirmation", async () => {
    const user = userEvent.setup();
    mockOpenApiApi.listPublications.mockResolvedValue([
      {
        id: "pub-disabled",
        public_id: "legacy_support",
        target_type: "agent",
        target_id: "agent-1",
        bound_user_id: "7",
        knowledge_base_id: "openapi-pub-disabled",
        name: "旧客服接口",
        status: "disabled",
        allowed_scopes: ["messages:create"],
      },
    ]);

    render(<OpenApiPage />);

    await user.click(await screen.findByRole("switch", { name: "仅显示启用" }));
    expect(await screen.findByText("旧客服接口")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "删除" }));
    const deleteButtons = await screen.findAllByRole("button", {
      name: /删\s*除/,
    });
    await user.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(mockOpenApiApi.deletePublication).toHaveBeenCalledWith(
        "pub-disabled",
      );
    });
    expect(screen.queryByText("旧客服接口")).not.toBeInTheDocument();
  });

  it("reuses the shared agent experience library in the knowledge tab", async () => {
    const user = userEvent.setup();

    render(<OpenApiPage />);

    await user.click(await screen.findByRole("tab", { name: "专属知识库" }));

    expect(
      await screen.findByTestId("shared-agent-experience-library"),
    ).toBeInTheDocument();
  });
});
