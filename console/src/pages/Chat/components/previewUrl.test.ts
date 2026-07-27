import { describe, expect, it, vi } from "vitest";
import { buildWorkspacePreviewUrl } from "./previewUrl";
import { getApiToken } from "../../../api/config";

vi.mock("../../../api/config", () => ({
  getApiUrl: (path: string) => `/api/user${path}`,
  getApiToken: vi.fn(() => ""),
}));

describe("buildWorkspacePreviewUrl", () => {
  it("embeds agent and chat context in the preview path so relative assets inherit it", () => {
    const url = buildWorkspacePreviewUrl({
      path: "pages/index.html",
      agentId: "fullstack_dev",
      chatId: "chat-123",
      version: 7,
    });

    expect(url).toBe(
      "/api/user/workspace/preview/__qwenpaw_preview__/fullstack_dev/chat-123/pages/index.html?v=7",
    );
  });

  it("falls back to query parameters when no chat id is available", () => {
    const url = buildWorkspacePreviewUrl({
      path: "index.html",
      agentId: "default",
    });

    expect(url).toBe("/api/user/workspace/preview/index.html?agent_id=default");
  });

  it("appends auth token for iframe requests when login auth is enabled", () => {
    vi.mocked(getApiToken).mockReturnValue("tok en+1");

    const url = buildWorkspacePreviewUrl({
      path: "index.html",
      agentId: "default",
      chatId: "chat-123",
      version: 2,
    });

    expect(url).toBe(
      "/api/user/workspace/preview/__qwenpaw_preview__/default/chat-123/index.html?v=2&token=tok+en%2B1",
    );
  });
});
