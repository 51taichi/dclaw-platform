import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("task detail page contract", () => {
  it("keeps mobile expert/mode, model, and skill selectors above the task composer", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("专家 / 模式");
    expect(source).toContain("选择专家 / 模式");
    expect(source).toContain("TASK_MODE_OPTIONS");
    expect(source).toContain("模型");
    expect(source).toContain("技能");
    expect(source).toContain("OptionPicker");
    expect(source).toContain('pickerType === "expertMode"');
    expect(source).toContain('pickerType === "model"');
    expect(source).toContain('pickerType === "skill"');
    expect(source).toContain("listModelOptions");
    expect(source).toContain("setActiveModel");
    expect(source).toContain("formatTaskPrompt");
    expect(source).toContain("activeMode: selectedTaskMode");
    expect(source).toContain("POLL_INTERVAL_MS");
    expect(source).toContain("setInterval");
    expect(source).toContain("clearInterval");
    expect(source).not.toContain("loadPendingTaskIntent");
    expect(source).not.toContain("clearPendingTaskIntent");
    expect(source).not.toContain("submitPendingIntent");
    expect(source).not.toContain("intent.expertTeamId");
    expect(source).not.toContain("showActionSheet");
  });

  it("styles selectors as compact mobile composer controls", () => {
    const styles = readPageSource("./index.scss");

    expect(styles).toContain("composer-toolbar");
    expect(styles).toContain("composer-chip");
  });

  it("removes the native WeChat button border layer from composer buttons", () => {
    const styles = readPageSource("./index.scss");

    expect(styles).toContain(".primary-button::after");
    expect(styles).toContain(".secondary-button::after");
    expect(styles).toContain("border: 0;");
  });

  it("renders task status with Chinese labels instead of raw backend codes", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("STATUS_LABELS");
    expect(source).toContain("completed: \"已完成\"");
    expect(source).toContain("running: \"执行中\"");
    expect(source).not.toContain("状态：{detail.task.display_status}");
  });
});
