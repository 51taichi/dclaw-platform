import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("Taro mini-program style config", () => {
  it("defines a device ratio for the active 375 design width", () => {
    const configPath = fileURLToPath(
      new URL("../config/index.ts", import.meta.url),
    );
    const source = readFileSync(configPath, "utf8");

    expect(source).toContain("designWidth: 375");
    expect(source).toMatch(/375:\s*2/);
  });
});
