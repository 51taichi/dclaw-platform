import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readComponentSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  expect(existsSync(sourcePath)).toBe(true);
  return readFileSync(sourcePath, "utf8");
}

describe("PrivacyAuthorization contract", () => {
  it("uses WeChat native privacy APIs and agreement button", () => {
    const source = readComponentSource("./index.tsx");

    expect(source).toContain("getPrivacySetting");
    expect(source).toContain("openPrivacyContract");
    expect(source).toContain("onNeedPrivacyAuthorization");
    expect(source).toContain('openType="agreePrivacyAuthorization"');
    expect(source).toContain("onAgreePrivacyAuthorization");
    expect(source).toContain("buttonId");
    expect(source).not.toContain("用户协议");
  });
});
