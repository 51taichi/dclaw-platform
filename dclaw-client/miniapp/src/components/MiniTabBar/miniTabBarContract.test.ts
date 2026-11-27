import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readComponentSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("mini tab bar contract", () => {
  it("renders the approved ordinary-user mini-program navigation", () => {
    const source = readComponentSource("./index.tsx");

    expect(source).toContain("工作台");
    expect(source).toContain("任务");
    expect(source).toContain("确认");
    expect(source).toContain("我的");
    expect(source).not.toContain('label: "我"');
    expect(source).toContain("mascotTab");
  });

  it("uses image-generated tab icon assets instead of hand-drawn placeholders", () => {
    const source = readComponentSource("./index.tsx");
    const styles = readComponentSource("./index.scss");

    expect(styles).toContain("mini-tabbar__center");
    expect(source).toContain("tabWorkbench");
    expect(source).toContain("tabTasks");
    expect(source).toContain("tabConfirm");
    expect(source).toContain("tabMe");
    expect(styles).not.toContain("mini-tabbar__icon-line");
    expect(styles).not.toContain("mini-tabbar__paw-toe");
  });

  it("keeps tab icons and labels aligned in a five-column navigation grid", () => {
    const styles = readComponentSource("./index.scss");

    expect(styles).toContain("mini-tabbar__grid");
    expect(styles).toContain("grid-template-columns: repeat(5, minmax(0, 1fr))");
    expect(styles).toContain("height: 52px");
    expect(styles).toContain("justify-content: flex-end");
    expect(styles).toContain("white-space: nowrap");
  });

  it("uses explicit active and inactive icon assets for tab color states", () => {
    const source = readComponentSource("./index.tsx");

    expect(source).toContain("tabWorkbenchActive");
    expect(source).toContain("tabWorkbenchInactive");
    expect(source).toContain("tabTasksActive");
    expect(source).toContain("tabTasksInactive");
    expect(source).toContain("tabConfirmActive");
    expect(source).toContain("tabConfirmInactive");
    expect(source).toContain("tabMeActive");
    expect(source).toContain("tabMeInactive");
  });

  it("adds subtle tab motion without distracting from the app content", () => {
    const source = readComponentSource("./index.tsx");
    const styles = readComponentSource("./index.scss");

    expect(source).toContain("getMobileState");
    expect(source).toContain("mini-tabbar__item--attention");
    expect(styles).toContain("@keyframes mini-tabbar-mascot-breathe");
    expect(styles).toContain("@keyframes mini-tabbar-active-pop");
    expect(styles).toContain("@keyframes mini-tabbar-attention-pulse");
    expect(styles).toContain("transition:");
  });
});
