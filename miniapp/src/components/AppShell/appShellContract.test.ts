import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("AppShell privacy contract", () => {
  it("mounts the WeChat privacy authorization handler on business pages", () => {
    const sourcePath = fileURLToPath(new URL("./index.tsx", import.meta.url));
    const source = readFileSync(sourcePath, "utf8");

    expect(source).toContain("PrivacyAuthorization");
  });
});
