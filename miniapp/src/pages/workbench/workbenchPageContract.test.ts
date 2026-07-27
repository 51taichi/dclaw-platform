import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("workbench page contract", () => {
  it("keeps the approved shortcut entries on the employee workbench without standalone knowledge search", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("我的任务");
    expect(source).toContain("知识库用法");
    expect(source).toContain("AI工具确认");
    expect(source).toContain("AIGC创意");
    expect(source).not.toContain("待确认操作");
    expect(source).not.toContain("知识搜索");
    expect(source).not.toContain("/pages/knowledge/index");
  });

  it("guides AIGC creative work to the Web version instead of confirmations", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("https://dclaw.deepmega.cn/");
    expect(source).toContain("openAigcWebGuide");
    expect(source).toContain("showModal");
    expect(source).toContain("setClipboardData");
    expect(source).toContain("请到 Web 版体验");
  });

  it("explains knowledge base use through the task flow instead of a standalone search page", () => {
    const source = readPageSource("./index.tsx");
    const styles = readPageSource("./index.scss");

    expect(source).toContain("openKnowledgeGuide");
    expect(source).toContain("shortcut--knowledge");
    expect(source).toContain("知识库怎么用");
    expect(source).toContain("知识库用法");
    expect(source).toContain("企业知识库");
    expect(source).toContain("个人知识库");
    expect(source).toContain("knowledgeGuideOpen");
    expect(source).toContain("knowledge-guide");
    expect(source).toContain("knowledge-guide__step");
    expect(source).toContain("任务目标里写明参考范围");
    expect(source).toContain("/pages/create-task/index");
    expect(source).not.toContain("/pages/knowledge/index");
    expect(source).not.toContain("1. 点“发起任务”。");
    expect(styles).toContain("knowledge-guide__panel");
    expect(styles).toContain("text-align: left");
  });

  it("uses image-generated shortcut assets from the selected visual direction", () => {
    const source = readPageSource("./index.tsx");
    const styles = readPageSource("./index.scss");

    expect(source).toContain("shortcutTasks");
    expect(source).toContain("shortcutKnowledge");
    expect(source).toContain("shortcutAi");
    expect(source).toContain("shortcutConfirm");
    expect(styles).not.toContain("shortcut__icon--tasks");
    expect(styles).not.toContain("shortcut__icon--knowledge");
    expect(styles).not.toContain("shortcut__icon--ai");
    expect(styles).not.toContain("shortcut__icon--confirm");
  });

  it("lays out the workbench shortcuts as four balanced columns", () => {
    const styles = readPageSource("./index.scss");

    expect(styles).toContain("grid-template-columns: repeat(4, minmax(0, 1fr));");
  });

  it("uses the framed mascot treatment from the selected visual direction", () => {
    const styles = readPageSource("./index.scss");

    expect(styles).toContain("hero-mascot-frame");
    expect(styles).toContain("background: #ffffff");
    expect(styles).toContain("box-shadow");
  });
});
