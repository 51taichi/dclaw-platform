import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageConfig(pagePath: string) {
  const sourcePath = fileURLToPath(new URL(pagePath, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("mini-program native navigation titles", () => {
  it("does not repeat the page title in the native nav bar when the page has an in-content title", () => {
    const titledContentPageConfigs = [
      "./workbench/index.config.ts",
      "./tasks/index.config.ts",
      "./confirmations/index.config.ts",
      "./me/index.config.ts",
      "./create-task/index.config.ts",
      "./task-detail/index.config.ts",
      "./knowledge/index.config.ts",
      "./result/index.config.ts",
    ];

    for (const pageConfig of titledContentPageConfigs) {
      expect(readPageConfig(pageConfig)).toContain(
        'navigationBarTitleText: ""',
      );
    }
  });

  it("keeps native nav titles on pages without an in-content page title", () => {
    const nativeTitlePageConfigs = [
      "./login/index.config.ts",
    ];

    for (const pageConfig of nativeTitlePageConfigs) {
      expect(readPageConfig(pageConfig)).toMatch(
        /navigationBarTitleText:\s*"[^\s"][^"]*"/,
      );
    }
  });
});
