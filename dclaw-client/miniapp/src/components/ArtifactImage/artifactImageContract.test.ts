import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("artifact image contract", () => {
  it("downloads protected workspace images before previewing them", () => {
    const sourcePath = fileURLToPath(new URL("./index.tsx", import.meta.url));
    const source = readFileSync(sourcePath, "utf8");

    expect(source).toContain("downloadArtifactFile");
    expect(source).toContain("previewImage");
    expect(source).toContain('mode="aspectFill"');
    expect(source).toContain("图片加载失败");
  });
});
