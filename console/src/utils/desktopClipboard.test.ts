import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock, isTauriMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  isTauriMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: invokeMock,
  isTauri: isTauriMock,
}));

import {
  isDesktopRuntime,
  readDesktopClipboardFiles,
} from "./desktopClipboard";

describe("readDesktopClipboardFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isTauriMock.mockReturnValue(true);
  });

  it("turns native clipboard payloads into browser files", async () => {
    invokeMock.mockResolvedValue([
      {
        name: "客户资料.pdf",
        mime_type: "application/pdf",
        base64_data: "cGRm",
      },
      {
        name: "clipboard.png",
        mime_type: "image/png",
        base64_data: "aW1hZ2U=",
      },
    ]);

    const files = await readDesktopClipboardFiles();

    expect(invokeMock).toHaveBeenCalledWith("read_clipboard_attachments");
    expect(files.map((file) => [file.name, file.type, file.size])).toEqual([
      ["客户资料.pdf", "application/pdf", 3],
      ["clipboard.png", "image/png", 5],
    ]);
    await expect(files[0].text()).resolves.toBe("pdf");
    await expect(files[1].text()).resolves.toBe("image");
  });

  it("does not invoke native clipboard outside the desktop app", async () => {
    isTauriMock.mockReturnValue(false);

    await expect(readDesktopClipboardFiles()).resolves.toEqual([]);
    expect(invokeMock).not.toHaveBeenCalled();
  });

  it("reports whether the page is running inside Tauri", () => {
    isTauriMock.mockReturnValue(true);
    expect(isDesktopRuntime()).toBe(true);
    isTauriMock.mockReturnValue(false);
    expect(isDesktopRuntime()).toBe(false);
  });
});
