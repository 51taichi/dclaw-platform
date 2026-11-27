import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { saveDialog, writeFile } = vi.hoisted(() => ({
  saveDialog: vi.fn(),
  writeFile: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  save: saveDialog,
}));

vi.mock("@tauri-apps/plugin-fs", () => ({
  writeFile,
}));

import { saveDownloadedBlob } from "./download";

describe("saveDownloadedBlob", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    Reflect.deleteProperty(window, "pywebview");
    document.body.innerHTML = "";
  });

  it("asks for a destination and writes the bytes in Tauri", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {},
    });
    saveDialog.mockResolvedValue("/chosen/客户方案.pdf");
    writeFile.mockResolvedValue(undefined);

    const saved = await saveDownloadedBlob(
      new Blob([new Uint8Array([37, 80, 68, 70])]),
      "客户方案.pdf",
    );

    expect(saveDialog).toHaveBeenCalledWith({
      defaultPath: "客户方案.pdf",
      title: "保存文件",
    });
    expect(writeFile).toHaveBeenCalledWith(
      "/chosen/客户方案.pdf",
      new Uint8Array([37, 80, 68, 70]),
    );
    expect(saved).toBe(true);
  });

  it("treats cancelling the Tauri save dialog as a non-error", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {},
    });
    saveDialog.mockResolvedValue(null);

    const saved = await saveDownloadedBlob(new Blob(["cancel"]), "report.pdf");

    expect(writeFile).not.toHaveBeenCalled();
    expect(saved).toBe(false);
  });

  it("passes downloaded bytes to the pywebview native save dialog", async () => {
    const saveBlob = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: { api: { save_blob: saveBlob } },
    });

    const saved = await saveDownloadedBlob(
      new Blob([new Uint8Array([80, 68, 70])]),
      "folder/report?.pdf",
    );

    expect(saveBlob).toHaveBeenCalledWith([80, 68, 70], "report-.pdf");
    expect(saved).toBe(true);
  });

  it("keeps browser downloads in the browser", async () => {
    const click = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName) => {
      const element = originalCreateElement(tagName);
      if (tagName === "a") {
        element.click = click;
      }
      return element;
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:download");
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});

    const saved = await saveDownloadedBlob(new Blob(["web"]), "report.pdf");

    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:download");
    expect(saved).toBe(true);
  });
});
