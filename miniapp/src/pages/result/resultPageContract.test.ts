import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("result page contract", () => {
  it("previews generated image artifacts and opens document artifacts", () => {
    const source = readPageSource("./index.tsx");
    const styles = readPageSource("./index.scss");

    expect(source).toContain("downloadArtifactFile");
    expect(source).toContain("saveArtifactImageToAlbum");
    expect(source).toContain("ArtifactImage");
    expect(source).toContain("isImageArtifact");
    expect(source).toContain("previewImage");
    expect(source).toContain("openDocument");
    expect(source).toContain("formatFileSize");
    expect(source).toContain("file.path !== file.name");
    expect(source).toContain("预览图片");
    expect(source).toContain("保存相册");
    expect(source).toContain("已保存到手机相册");
    expect(source).toContain("需要相册权限");
    expect(source).toContain("打开文件");
    expect(source).toContain(
      "需要转发或另存时，可打开文件后使用右上角菜单。",
    );
    expect(source).toContain("继续打开");
    expect(styles).toContain("file-card--image");
    expect(styles).toContain("file-preview");
    expect(styles).toContain("file-action--save-image");
    expect(styles).toContain("file-action");
  });
});
