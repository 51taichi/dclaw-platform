import { describe, expect, it } from "vitest";
import { buildWorkbenchPrompt, WORKBENCH_PROMPT_KEYS } from "./promptTemplates";

const t = (_key: string, fallback: string) => fallback;

describe("workbench prompt templates", () => {
  it("provides a concrete prompt for every quick tag", () => {
    for (const key of WORKBENCH_PROMPT_KEYS) {
      const prompt = buildWorkbenchPrompt(key, t);

      expect(prompt).toContain("请");
      expect(prompt.length).toBeGreaterThan(30);
      expect(prompt).not.toBe(`${key}: `);
    }
  });

  it("falls back to an editable task prompt for unknown tags", () => {
    expect(buildWorkbenchPrompt("unknown", t)).toBe(
      "请帮我完成一个任务：\n目标：\n背景：\n期望产物：",
    );
  });
});
