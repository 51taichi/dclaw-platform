import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("confirmations page contract", () => {
  it("keeps the tab bar confirmation attention state in sync with pending items", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("setPendingConfirmationCount");
    expect(source).toContain("response.length");
    expect(source).toContain("nextItems.length");
  });
});
