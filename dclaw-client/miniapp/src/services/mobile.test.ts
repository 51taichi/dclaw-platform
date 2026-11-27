import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tarojs/taro", () => ({
  default: {
    downloadFile: vi.fn(),
    saveImageToPhotosAlbum: vi.fn(),
  },
}));

vi.mock("./api", () => ({
  buildRequestUrl: vi.fn((prefix: string, path: string) => `http://local${prefix}${path}`),
  request: vi.fn(),
}));

vi.mock("./auth", () => ({
  getAuthToken: vi.fn(() => "token-1"),
}));

import Taro from "@tarojs/taro";

import { request } from "./api";
import {
  archiveTask,
  deleteTask,
  downloadArtifactFile,
  saveArtifactImageToAlbum,
} from "./mobile";

const mockRequest = vi.mocked(request);
const mockDownloadFile = vi.mocked(Taro.downloadFile);
const mockSaveImageToPhotosAlbum = vi.mocked(Taro.saveImageToPhotosAlbum);

describe("mobile service task mutations", () => {
  beforeEach(() => {
    mockRequest.mockReset();
    mockDownloadFile.mockReset();
    mockSaveImageToPhotosAlbum.mockReset();
  });

  it("archives a task through the mobile task endpoint", async () => {
    mockRequest.mockResolvedValueOnce({
      archived: true,
      id: "chat-1",
      archived_at: "2026-07-07T12:00:00+00:00",
    });

    await archiveTask("chat/1");

    expect(mockRequest).toHaveBeenCalledWith("/mobile/tasks/chat%2F1/archive", {
      method: "POST",
    });
  });

  it("deletes a task through the mobile task endpoint", async () => {
    mockRequest.mockResolvedValueOnce({ deleted: true, id: "chat-1" });

    await deleteTask("chat/1");

    expect(mockRequest).toHaveBeenCalledWith("/mobile/tasks/chat%2F1", {
      method: "DELETE",
    });
  });

  it("downloads artifacts with encoded file paths and auth headers", async () => {
    mockDownloadFile.mockResolvedValueOnce({
      statusCode: 200,
      tempFilePath: "wxfile://tmp/image.png",
      errMsg: "downloadFile:ok",
    } as never);

    const tempPath = await downloadArtifactFile("chat/1", "images/结果 图.png");

    expect(tempPath).toBe("wxfile://tmp/image.png");
    expect(Taro.downloadFile).toHaveBeenCalledWith(
      expect.objectContaining({
        url: "http://local/api/user/workspace/files/download/images/%E7%BB%93%E6%9E%9C%20%E5%9B%BE.png?chatId=chat%2F1",
        header: { Authorization: "Bearer token-1" },
        timeout: 20000,
      }),
    );
  });

  it("saves an image artifact to the phone photo album", async () => {
    mockDownloadFile.mockResolvedValueOnce({
      statusCode: 200,
      tempFilePath: "wxfile://tmp/image.png",
      errMsg: "downloadFile:ok",
    } as never);
    mockSaveImageToPhotosAlbum.mockResolvedValueOnce({
      errMsg: "saveImageToPhotosAlbum:ok",
    } as never);

    await saveArtifactImageToAlbum("chat-1", "media/imagegen/image.png");

    expect(Taro.saveImageToPhotosAlbum).toHaveBeenCalledWith({
      filePath: "wxfile://tmp/image.png",
    });
  });
});
