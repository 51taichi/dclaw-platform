import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readComponentSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("option picker contract", () => {
  it("shows concise row explanations without a separate selected detail panel", () => {
    const source = readComponentSource("./index.tsx");
    const styles = readComponentSource("./index.scss");

    expect(source).toContain("option-picker__item-name");
    expect(source).toContain("option-picker__item-desc");
    expect(source).toContain("option-picker__badge");
    expect(source).toContain("option-picker__check");
    expect(source).not.toContain("selectedOption");
    expect(source).not.toContain("option-picker__detail");
    expect(source).not.toContain("option-picker__tool");
    expect(source).not.toContain("Tools - Built-in");
    expect(styles).toContain("option-picker__item-desc");
    expect(styles).not.toContain("option-picker__detail");
    expect(styles).not.toContain("option-picker__tool");
  });
});
