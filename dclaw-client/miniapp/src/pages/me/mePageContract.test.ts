import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("me page contract", () => {
  it("shows the signed-in account instead of a hardcoded ordinary-user profile", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("我的");
    expect(source).toContain("getStoredUsername");
    expect(source).toContain("当前账号");
    expect(source).not.toContain("DClaw 普通用户");
    expect(source).not.toContain("普通用户");
    expect(source).not.toContain("员工端");
    expect(source).not.toContain("普通员工");
  });

  it("keeps only actionable entries with real page or feedback handlers", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("/pages/tasks/index");
    expect(source).toContain("/pages/confirmations/index");
    expect(source).toContain("帮助与反馈");
    expect(source).toContain("showModal");
    expect(source).not.toContain("通知设置");
  });

  it("keeps the tab bar confirmation attention state in sync with workbench stats", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("applyWorkbenchSummary");
  });

  it("keeps the logout button clear of the fixed bottom tab bar", () => {
    const source = readPageSource("./index.scss");

    expect(source).toContain(".logout-button");
    expect(source).toContain("margin-bottom: 24px;");
  });

  it("removes the native WeChat button border layer from the logout button", () => {
    const source = readPageSource("./index.scss");

    expect(source).toContain(".logout-button::after");
    expect(source).toContain("border: 0;");
  });
});
