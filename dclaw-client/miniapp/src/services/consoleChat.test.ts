import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  request: vi.fn(),
}));

import { request } from "./api";
import { createAndSubmitTask, sendTaskPrompt } from "./consoleChat";

const mockRequest = vi.mocked(request);

describe("createAndSubmitTask", () => {
  beforeEach(() => {
    mockRequest.mockReset();
  });

  it("creates a craft task chat and sends the initial prompt without default expert team metadata", async () => {
    mockRequest
      .mockResolvedValueOnce({
        id: "chat-1",
        session_id: "session-1",
        user_id: "user-1",
        channel: "console",
        name: "销售分析",
        meta: {
          agent_id: "data-analysis",
        },
      })
      .mockResolvedValueOnce("ok");

    const chat = await createAndSubmitTask({
      name: "销售分析",
      prompt: "/[xlsx]\n\n生成销售分析",
      agentId: "data-analysis",
      skillName: "xlsx",
    });

    expect(chat.id).toBe("chat-1");
    const createCall = mockRequest.mock.calls[0];
    const promptCall = mockRequest.mock.calls[1];

    expect(mockRequest).toHaveBeenNthCalledWith(
      1,
      "/chats",
      expect.objectContaining({
        method: "POST",
        header: { "X-Agent-Id": "data-analysis" },
        data: expect.objectContaining({
          name: "销售分析",
          session_id: "",
          user_id: "default",
          channel: "console",
          meta: expect.objectContaining({
            mode: "task",
            active_mode: "craft",
            agent_id: "data-analysis",
          }),
        }),
      }),
    );
    expect(createCall[1]?.data).not.toHaveProperty("expert_team_id");
    expect(createCall[1]?.data.meta).not.toHaveProperty("expert_team_id");

    expect(mockRequest).toHaveBeenNthCalledWith(
      2,
      "/console/chat",
      expect.objectContaining({
        method: "POST",
        header: { "X-Agent-Id": "data-analysis" },
        data: expect.objectContaining({
          input: [{ role: "user", content: "/[xlsx]\n\n生成销售分析" }],
          chat_id: "chat-1",
          session_id: "session-1",
          stream: false,
          meta: expect.objectContaining({
            selected_skill: "xlsx",
            agent_id: "data-analysis",
            active_mode: "craft",
          }),
        }),
      }),
    );
    expect(promptCall[1]?.data).not.toHaveProperty("expert_team_id");
    expect(promptCall[1]?.data.meta).not.toHaveProperty("expert_team_id");
  });

  it("sends task prompts with explicit expert team metadata when selected", async () => {
    mockRequest.mockResolvedValueOnce({
      chat_id: "chat-1",
      session_id: "chat-1",
      status: "started",
    });

    await sendTaskPrompt({
      chatId: "chat-1",
      sessionId: "chat-1",
      userId: "2",
      agentId: "default",
      prompt: "你是？",
      expertTeamId: "deep_research_team",
    });

    expect(mockRequest).toHaveBeenCalledWith(
      "/console/chat",
      expect.objectContaining({
        data: expect.objectContaining({
          session_id: "chat-1",
          user_id: "2",
          channel: "console",
          stream: false,
          expert_team_id: "deep_research_team",
          meta: expect.objectContaining({
            expert_team_id: "deep_research_team",
          }),
        }),
      }),
    );
  });

  it("uses the precreated chat id when the created task has no session id", async () => {
    mockRequest
      .mockResolvedValueOnce({
        id: "chat-without-session",
        session_id: "",
        user_id: "user-1",
        channel: "console",
        name: "空会话任务",
        meta: {
          agent_id: "default",
          active_mode: "craft",
        },
      })
      .mockResolvedValueOnce("ok");

    await createAndSubmitTask({
      name: "空会话任务",
      prompt: "整理项目进展",
    });

    expect(mockRequest).toHaveBeenNthCalledWith(
      2,
      "/console/chat",
      expect.objectContaining({
        data: expect.objectContaining({
          chat_id: "chat-without-session",
          session_id: "chat-without-session",
          meta: expect.objectContaining({
            root_session_id: "chat-without-session",
          }),
        }),
      }),
    );
  });

  it("preserves expert mode active_mode as an empty string", async () => {
    mockRequest.mockResolvedValueOnce({
      id: "chat-2",
      session_id: "session-2",
      user_id: "user-1",
      channel: "console",
      name: "专家任务",
      meta: {
        agent_id: "data_analysis",
        active_mode: "",
      },
    });
    mockRequest.mockResolvedValueOnce("ok");

    await createAndSubmitTask({
      name: "专家任务",
      prompt: "分析销售趋势",
      agentId: "data_analysis",
      activeMode: "",
    });

    expect(mockRequest).toHaveBeenNthCalledWith(
      1,
      "/chats",
      expect.objectContaining({
        data: expect.objectContaining({
          meta: expect.objectContaining({
            agent_id: "data_analysis",
            active_mode: "",
          }),
        }),
      }),
    );
    expect(mockRequest).toHaveBeenNthCalledWith(
      2,
      "/console/chat",
      expect.objectContaining({
        data: expect.objectContaining({
          meta: expect.objectContaining({
            agent_id: "data_analysis",
            active_mode: "",
          }),
        }),
      }),
    );
  });
});
