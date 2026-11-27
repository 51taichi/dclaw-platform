import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PAGE_NAMES = [
  "workbench",
  "create-task",
  "tasks",
  "task-detail",
  "confirmations",
  "knowledge",
  "result",
  "me",
  "login",
];

function readSource(relativePath: string) {
  const sourcePath = fileURLToPath(new URL(relativePath, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("mini-program page sharing", () => {
  it("registers friend and timeline sharing in the shared hook", () => {
    const source = readSource("./hooks/usePageShare.ts");

    expect(source).toContain("useShareAppMessage");
    expect(source).toContain("useShareTimeline");
  });

  it("enables and registers sharing on every page", () => {
    for (const pageName of PAGE_NAMES) {
      const pageSource = readSource(`./pages/${pageName}/index.tsx`);
      const pageConfig = readSource(`./pages/${pageName}/index.config.ts`);

      expect(pageSource).toContain("usePageShare({");
      expect(pageConfig).toContain("enableShareAppMessage: true");
      expect(pageConfig).toContain("enableShareTimeline: true");
    }
  });

  it("keeps task identifiers in task detail and result share paths", () => {
    for (const pageName of ["task-detail", "result"]) {
      const pageSource = readSource(`./pages/${pageName}/index.tsx`);

      expect(pageSource).toMatch(/path:.*chatId/s);
      expect(pageSource).toContain("encodeURIComponent(chatId)");
    }
  });

  it("preserves both share handlers in every generated WeChat page", () => {
    for (const pageName of PAGE_NAMES) {
      const generatedPage = readSource(`../dist/pages/${pageName}/index.js`);

      expect(generatedPage).toContain("enableShareAppMessage=!0");
      expect(generatedPage).toContain("enableShareTimeline=!0");
    }
  });
});
