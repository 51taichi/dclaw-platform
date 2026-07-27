import { render, screen, waitFor } from "@testing-library/react";
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
      listKnowledgeDocuments: vi.fn(),
      uploadKnowledgeDocument: vi.fn(),
      syncKnowledgeDocument: vi.fn(),
      deleteKnowledgeDocument: vi.fn(),
      listApps: vi.fn(),
      createApp: vi.fn(),
      listKeys: vi.fn(),
      createKey: vi.fn(),
      revokeKey: vi.fn(),
      listInvocations: vi.fn(),
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
    ]);
    mockOpenApiApi.listKeys.mockResolvedValue([]);
    mockOpenApiApi.listInvocations.mockResolvedValue([]);
    mockOpenApiApi.listKnowledgeDocuments.mockResolvedValue([]);
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

  it("loads publications and shows a one-time secret after creating a key", async () => {
    const user = userEvent.setup();

    render(<OpenApiPage />);

    expect((await screen.findAllByText("客服专家")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("CRM")).length).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText("knowledge-owner (user)")).length,
    ).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /创建 API Key/ }));

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
    await user.click(screen.getByRole("button", { name: "创建外部应用" }));

    await waitFor(() => {
      expect(mockOpenApiApi.createApp).toHaveBeenCalledWith({
        name: "Mini Program",
        ip_allowlist: ["127.0.0.1", "10.0.0.8"],
      });
    });
  });

  it("does not allow creating a key for a disabled publication", async () => {
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

    const button = await screen.findByRole("button", { name: /创建 API Key/ });

    expect(button).toBeDisabled();
    expect(mockOpenApiApi.createKey).not.toHaveBeenCalled();
  });
});
