import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import ExpertsPage from "./index";

const { mockListAgents, mockListExpertTeams, mockUseAgentStore } = vi.hoisted(
  () => {
    const store = Object.assign(
      vi.fn(() => ({
        setSelectedAgent: vi.fn(),
        setActiveMode: vi.fn(),
        setSelectedExpertTeam: vi.fn(),
      })),
      {
        getState: vi.fn(() => ({
          selectedAgent: "default",
          getLastChatId: vi.fn(),
        })),
      },
    );
    return {
      mockListAgents: vi.fn(),
      mockListExpertTeams: vi.fn(),
      mockUseAgentStore: store,
    };
  },
);

vi.mock("../../api/modules/agents", () => ({
  agentsApi: { listAgents: mockListAgents },
}));

vi.mock("../../api/modules/expertTeams", () => ({
  expertTeamsApi: { listExpertTeams: mockListExpertTeams },
}));

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: mockUseAgentStore,
}));

vi.mock("../Chat/sessionApi", () => ({
  default: { reset: vi.fn() },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

describe("ExpertsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListAgents.mockResolvedValue({
      agents: [
        {
          id: "luyu_dclaw_agent",
          name: "陆羽 AI 流量操盘手",
          description: "带客户完成业务理解、流量诊断、内容执行与数据复盘。",
          enabled: true,
          agent_type: "sealed",
          avatar: "data:image/png;base64,luyu-avatar",
          open_api_enabled: false,
        },
        {
          id: "ordinary-agent",
          name: "普通专家",
          description: "处理普通任务。",
          enabled: true,
          agent_type: "standard",
          open_api_enabled: false,
        },
      ],
    });
    mockListExpertTeams.mockResolvedValue([]);
  });

  it("renders super experts in their own styled section with avatar and medal", async () => {
    renderWithProviders(<ExpertsPage />, { initialEntries: ["/experts"] });

    await waitFor(() => expect(mockListAgents).toHaveBeenCalled());

    const superSection = await screen.findByRole("region", {
      name: "超级专家",
    });
    expect(
      within(superSection).getByText(
        "单个智能体超级专家，可以调用平台授权的互动能力。",
      ),
    ).toBeVisible();
    expect(
      within(superSection).getByAltText("陆羽 AI 流量操盘手头像"),
    ).toHaveAttribute("src", "data:image/png;base64,luyu-avatar");
    expect(within(superSection).getByLabelText("超级专家")).toBeVisible();
    expect(
      superSection.querySelector('[class*="superExpertCard"]'),
    ).toBeInTheDocument();

    const ordinarySection = screen.getByRole("region", { name: "专家" });
    expect(within(ordinarySection).getByText("普通专家")).toBeVisible();
    expect(
      within(ordinarySection).queryByText("陆羽 AI 流量操盘手"),
    ).not.toBeInTheDocument();
    expect(
      within(ordinarySection).queryByLabelText("超级专家"),
    ).not.toBeInTheDocument();
  });

  it("uses frontend usage configuration for every expert card kind", async () => {
    mockListAgents.mockResolvedValue({
      agents: [
        {
          id: "luyu_dclaw_agent",
          name: "陆羽 AI 流量操盘手",
          description: "带客户完成业务理解、流量诊断、内容执行与数据复盘。",
          enabled: true,
          agent_type: "sealed",
          avatar: "data:image/png;base64,luyu-avatar",
          open_api_enabled: false,
        },
        {
          id: "fullstack_dev",
          name: "全栈开发专家",
          description: "处理软件开发任务。",
          enabled: true,
          agent_type: "standard",
          open_api_enabled: false,
        },
      ],
    });
    mockListExpertTeams.mockResolvedValue([
      {
        id: "ai_video_team",
        name: "AI 视频创作团队",
        description: "完成视频创作任务。",
        category: "content",
        tags: ["视频策划"],
        icon: "🎬",
        enabled: true,
        leader_agent_id: "content_creation",
        members: [],
        workflow: [],
        usage_count: 321,
        source: "builtin",
      },
    ]);

    renderWithProviders(<ExpertsPage />, { initialEntries: ["/experts"] });

    const superSection = await screen.findByRole("region", {
      name: "超级专家",
    });
    const teamSection = screen.getByRole("region", { name: "专家团" });
    const ordinarySection = screen.getByRole("region", { name: "专家" });

    expect(within(superSection).getByText("0 次使用")).toBeVisible();
    expect(within(teamSection).getByText("0 次使用")).toBeVisible();
    expect(
      within(teamSection).queryByText("321 次使用"),
    ).not.toBeInTheDocument();
    expect(within(ordinarySection).getByText("12,850 次使用")).toBeVisible();
  });
});
