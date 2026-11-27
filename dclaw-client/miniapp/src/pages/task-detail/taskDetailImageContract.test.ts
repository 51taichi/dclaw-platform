import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("task detail image contract", () => {
  it("renders conversation images and image artifact thumbnails", () => {
    const source = readPageSource("./index.tsx");
    const styles = readPageSource("./index.scss");

    expect(source).toContain("messageImagePaths");
    expect(source).toContain("message.images.map");
    expect(source).toContain("ArtifactImage");
    expect(source).toContain('artifact.kind === "image"');
    expect(styles).toContain("message-images");
    expect(styles).toContain("artifact-row__preview");
  });
});
