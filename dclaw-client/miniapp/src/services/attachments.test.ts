import { describe, expect, it, vi } from "vitest";

vi.mock("@tarojs/taro", () => ({
  default: {
    getStorageSync: vi.fn(() => "token-1"),
    uploadFile: vi.fn(),
  },
}));

import Taro from "@tarojs/taro";

import { uploadConsoleAttachment } from "./attachments";

describe("uploadConsoleAttachment", () => {
  it("uploads a selected local file to the console upload endpoint", async () => {
    vi.mocked(Taro.uploadFile).mockResolvedValueOnce({
      statusCode: 200,
      data: JSON.stringify({
        url: "/uploads/report.pdf",
        file_name: "report.pdf",
      }),
      errMsg: "uploadFile:ok",
    } as never);

    const result = await uploadConsoleAttachment({
      path: "wxfile://tmp/report.pdf",
      name: "report.pdf",
    });

    expect(result).toEqual({
      name: "report.pdf",
      url: "/uploads/report.pdf",
      markdown: "📎 [report.pdf](/uploads/report.pdf)",
    });
    expect(Taro.uploadFile).toHaveBeenCalledWith(
      expect.objectContaining({
        filePath: "wxfile://tmp/report.pdf",
        name: "file",
        header: { Authorization: "Bearer token-1" },
      }),
    );
    const uploadOptions = vi.mocked(Taro.uploadFile).mock.calls[0]?.[0];
    expect(uploadOptions?.url).toContain("/api/user/console/upload");
  });
});
