import { afterEach, describe, expect, it, vi } from "vitest";
import { message } from "antd";

import { downloadAssetSource } from "./assetDownload";

vi.mock("antd", () => ({
  message: {
    error: vi.fn(),
    loading: vi.fn(),
    success: vi.fn(),
  },
}));

describe("downloadAssetSource", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document
      .querySelectorAll("[data-aigc-download-link]")
      .forEach((element) => element.remove());
  });

  it("shows a loading toast before starting an image download", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );

    await downloadAssetSource({
      source: "blob:generated-image",
      label: "image.png",
    });

    expect(message.loading).toHaveBeenCalledWith({
      content: "正在下载图片...",
      duration: 0,
      key: expect.any(String),
    });
    expect(message.success).toHaveBeenCalledWith({
      content: "图片已开始下载",
      duration: 2,
      key: expect.any(String),
    });
  });

  it("replaces the loading toast with an error toast when download fails", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      }),
    );

    await downloadAssetSource({
      source: "/api/user/aigc-studio/assets/missing/file",
      label: "missing.png",
    });

    expect(message.loading).toHaveBeenCalledWith({
      content: "正在下载图片...",
      duration: 0,
      key: expect.any(String),
    });
    expect(message.error).toHaveBeenCalledWith({
      content: "图片下载失败",
      key: expect.any(String),
    });
    expect(warnSpy).toHaveBeenCalled();
  });
});
