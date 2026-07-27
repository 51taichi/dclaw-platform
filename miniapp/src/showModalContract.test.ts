import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const MINIAPP_SRC = join(process.cwd(), "src");
const SEARCH_ROOTS = ["components", "pages", "services"].map((dir) =>
  join(MINIAPP_SRC, dir),
);
const BUTTON_TEXT_PATTERN = /\b(confirmText|cancelText):\s*"([^"]+)"/g;
const CHINESE_CHARACTER_PATTERN = /[\u4e00-\u9fff]/g;

function sourceFiles(root: string): string[] {
  return readdirSync(root).flatMap((entry) => {
    const path = join(root, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(ts|tsx)$/.test(entry) ? [path] : [];
  });
}

function chineseLength(value: string): number {
  return value.match(CHINESE_CHARACTER_PATTERN)?.length ?? 0;
}

describe("showModal button text contract", () => {
  it("keeps WeChat modal button labels within the 4-Chinese-character limit", () => {
    const violations = SEARCH_ROOTS.flatMap(sourceFiles).flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return [...source.matchAll(BUTTON_TEXT_PATTERN)]
        .filter((match) => chineseLength(match[2]) > 4)
        .map(
          (match) =>
            `${relative(process.cwd(), file)} ${match[1]} "${match[2]}"`,
        );
    });

    expect(violations).toEqual([]);
  });
});
