import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readComponentSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("task card visual contract", () => {
  it("uses the image-generated task icon asset instead of a plain color block", () => {
    const source = readComponentSource("./index.tsx");
    const styles = readComponentSource("./index.scss");

    expect(source).toContain("taskFile");
    expect(styles).not.toContain("&--running &__icon");
    expect(styles).not.toContain("&--pending_confirmation &__icon");
    expect(styles).not.toContain("&--completed &__icon");
    expect(styles).not.toContain("&--failed &__icon");
  });

  it("makes running tasks visually obvious for the non-streaming miniapp flow", () => {
    const source = readComponentSource("./index.tsx");
    const styles = readComponentSource("./index.scss");

    expect(source).toContain('task.display_status === "running"');
    expect(source).toContain("task-card__running-indicator");
    expect(source).toContain("执行中");
    expect(styles).toContain("&--running");
    expect(styles).toContain("@keyframes task-running-pulse");
    expect(styles).toContain("@keyframes task-running-bar");
  });

  it("keeps a compact more-action target for archive and delete actions", () => {
    const source = readComponentSource("./index.tsx");
    const styles = readComponentSource("./index.scss");

    expect(source).toContain("onMore");
    expect(source).toContain("task-card__more");
    expect(source).toContain("stopPropagation");
    expect(styles).toContain("&__more");
  });
});
