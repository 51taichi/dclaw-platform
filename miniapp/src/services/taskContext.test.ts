import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  request: vi.fn(),
}));

import { request } from "./api";
import {
  formatTaskPrompt,
  getExpertModeSelectionUnavailableMessage,
  getSkillSelectionUnavailableMessage,
  isTaskMode,
  listAgentOptions,
  listSkillOptions,
  toExpertModeOptions,
  toSkillOptions,
  type MobileSkillOption,
} from "./taskContext";

const mockRequest = vi.mocked(request);

describe("mobile task context helpers", () => {
  beforeEach(() => {
    mockRequest.mockReset();
  });

  it("wraps selected skills with the same invocation syntax as the web composer", () => {
    const skill: MobileSkillOption = {
      id: "skill_creator",
      name: "技能生成器",
    };

    expect(formatTaskPrompt("帮我生成一个技能", skill)).toBe(
      "/[skill_creator]\n\n帮我生成一个技能",
    );
  });

  it("formats plan and ask task prompts like the web composer", () => {
    expect(formatTaskPrompt("整理项目进展", null, "plan")).toBe(
      "/plan 整理项目进展",
    );
    expect(formatTaskPrompt("这个方案是否合理？", null, "ask")).toBe(
      "[Ask Mode: 仅回答问题，不要执行任何文件操作、命令执行或工具调用]\n这个方案是否合理？",
    );
  });

  it("keeps skill invocation outside the selected mode prefix", () => {
    const skill: MobileSkillOption = {
      id: "xlsx",
      name: "表格处理",
    };

    expect(formatTaskPrompt("生成销售摘要", skill, "plan")).toBe(
      "/[xlsx]\n\n/plan 生成销售摘要",
    );
  });

  it("recognizes web-compatible task modes", () => {
    expect(isTaskMode("craft")).toBe(true);
    expect(isTaskMode("plan")).toBe(true);
    expect(isTaskMode("ask")).toBe(true);
    expect(isTaskMode("default")).toBe(false);
  });

  it("builds the expert/mode picker with web-compatible default modes first", () => {
    expect(toExpertModeOptions([]).map((option) => option.name)).toEqual([
      "Craft",
      "Plan",
      "Ask",
    ]);
    expect(
      toExpertModeOptions([
        { id: "default", name: "Default" },
        { id: "data_analysis", name: "数据分析专家" },
      ]).map((option) => option.name),
    ).toEqual(["Craft", "Plan", "Ask", "数据分析专家"]);
  });

  it("explains when to use each built-in mode", () => {
    const options = toExpertModeOptions([]);

    expect(options[0]).toMatchObject({
      id: "mode:craft",
      badge: "推荐",
      description: expect.stringContaining("全自动执行"),
      tools: ["文件读写操作", "终端命令执行", "自动化网页搜索"],
    });
    expect(options[1]).toMatchObject({
      id: "mode:plan",
      description: expect.stringContaining("方案规划与任务拆解"),
      tools: ["深度逻辑推理", "架构方案设计", "开发任务拆解"],
    });
    expect(options[2]).toMatchObject({
      id: "mode:ask",
      description: expect.stringContaining("纯粹的技术问答"),
      tools: ["快速技术咨询", "代码逻辑分析", "框架库知识检索"],
    });
  });

  it("keeps default pool skills available when not installed in a workspace", () => {
    const skills = toSkillOptions(
      [],
      [
        {
          name: "skill_creator",
          description: "Generate skills",
          config: {
            display_name: "技能生成器",
            is_default: true,
          },
        },
      ],
    );

    expect(skills).toEqual([
      {
        id: "skill_creator",
        name: "技能生成器",
        description: "Generate skills",
        isDefault: true,
        isPrivate: false,
      },
    ]);
  });

  it("filters hidden installed and hidden default skills from mobile choices", () => {
    const skills = toSkillOptions(
      [
        {
          name: "visible_installed",
          description: "Visible installed",
          enabled: true,
        },
        {
          name: "hidden_installed",
          description: "Hidden installed",
          enabled: true,
          client_visible: false,
        },
      ],
      [
        {
          name: "hidden_installed",
          description: "Hidden installed",
          client_visible: false,
        },
        {
          name: "hidden_default",
          description: "Hidden default",
          client_visible: false,
          config: {
            is_default: true,
          },
        },
      ],
    );

    expect(skills.map((skill) => skill.id)).toEqual(["visible_installed"]);
  });

  it("keeps the backend agent display name without inventing a product alias", async () => {
    mockRequest.mockResolvedValueOnce({
      agents: [
        {
          id: "default",
          name: "Default",
          description: "Default DClaw agent",
          enabled: true,
        },
      ],
    });

    await expect(listAgentOptions()).resolves.toEqual([
      {
        id: "default",
        name: "Default",
        description: "Default DClaw agent",
      },
    ]);
  });

  it("refreshes skills when the initial workspace and pool lists are empty", async () => {
    mockRequest
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          name: "skill_creator",
          description: "Generate skills",
          config: {
            display_name: "技能生成器",
            is_default: true,
          },
        },
      ]);

    await expect(listSkillOptions("default")).resolves.toEqual([
      {
        id: "skill_creator",
        name: "技能生成器",
        description: "Generate skills",
        isDefault: true,
        isPrivate: false,
      },
    ]);
    expect(mockRequest).toHaveBeenNthCalledWith(
      3,
      "/skills/refresh",
      expect.objectContaining({
        method: "POST",
        header: { "X-Agent-Id": "default" },
      }),
    );
    expect(mockRequest).toHaveBeenNthCalledWith(
      4,
      "/skills/pool/refresh",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });

  it("explains when there is nothing meaningful to choose", () => {
    expect(
      getExpertModeSelectionUnavailableMessage([
        { id: "default", name: "Default" },
      ]),
    ).toBe("");
    expect(getExpertModeSelectionUnavailableMessage([])).toBe("");
    expect(
      getExpertModeSelectionUnavailableMessage([
        { id: "default", name: "Default" },
        { id: "data_analysis", name: "数据分析专家" },
      ]),
    ).toBe("");
    expect(getSkillSelectionUnavailableMessage([])).toBe("暂无可选技能");
  });
});
