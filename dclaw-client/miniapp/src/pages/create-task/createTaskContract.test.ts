import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

function countMatches(source: string, pattern: string) {
  return source.split(pattern).length - 1;
}

describe("create task page contract", () => {
  it("presents mobile task delegation instead of a prompt-only form", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain('useState<TaskEntryType>("chat")');
    expect(source).toContain("对话任务");
    expect(source).toContain("AIGC 创意项目");
    expect(source).toContain('selectedEntryType === "chat"');
    expect(source).toContain('selectEntryType("aigc")');
    expect(source).toContain("选择专家 / 模式");
    expect(source).toContain("专家 / 模式");
    expect(source).toContain("TASK_MODE_OPTIONS");
    expect(source).toContain("模型");
    expect(source).toContain("技能");
    expect(source).toContain("补充材料");
    expect(source).toContain("描述任务目标");
    expect(source).toContain("AIGC 创意项目");
    expect(source).toContain("https://dclaw.deepmega.cn/");
    expect(source).toContain("showModal");
    expect(source).toContain("交给 DClaw 执行");
    expect(source).toContain("listAgentOptions");
    expect(source).toContain("listModelOptions");
    expect(source).toContain("setActiveModel");
    expect(source).toContain("listSkillOptions");
    expect(source).toContain("formatTaskPrompt");
    expect(source).toContain("OptionPicker");
    expect(source).not.toContain('className="card aigc-card"');
    expect(source).not.toContain("当前执行上下文");
    expect(source).not.toContain("你想完成什么？");
  });

  it("uses an in-page picker for agent, model, and skill selection instead of action sheets", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain('pickerType === "expertMode"');
    expect(source).toContain('pickerType === "model"');
    expect(source).toContain('pickerType === "skill"');
    expect(countMatches(source, "showActionSheet")).toBe(1);
  });

  it("starts the task prompt immediately and returns the user to the task queue", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("createAndSubmitTask");
    expect(source).toContain("prompt: formattedPrompt");
    expect(source).toContain("activeMode: selectedTaskMode");
    expect(source).toContain("skillName: selectedSkill?.id");
    expect(source).toContain("/pages/tasks/index");
    expect(source).toContain("任务已交给 DClaw");
    expect(source).not.toContain("savePendingTaskIntent");
    expect(source).not.toContain("/pages/task-detail/index?chatId=");
    expect(source).not.toContain("sales-support");
    expect(source).not.toContain("DEFAULT_EXPERT_TEAM_ID");
  });

  it("keeps create-task styles organized around entry type, context, materials, goal, aigc guide, and templates", () => {
    const styles = readPageSource("./index.scss");

    expect(styles).toContain("task-type-switch");
    expect(styles).toContain("chat-task-content");
    expect(styles).toContain("context-card");
    expect(styles).toContain("material-card");
    expect(styles).toContain("goal-card");
    expect(styles).toContain("aigc-guide-card");
    expect(styles).toContain("template-list");
  });

  it("includes a common task template that highlights enterprise and personal knowledge bases", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("结合企业知识库和个人知识库");
    expect(source).toContain("常用任务");
  });
});
