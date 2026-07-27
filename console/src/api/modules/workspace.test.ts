import { afterEach, describe, expect, it, vi } from "vitest";
import { workspaceApi } from "./workspace";

vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api/user${path}`,
}));

vi.mock("../authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "Bearer test-token" }),
}));

describe("workspaceApi downloads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("downloads only the current chat artifact package", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response("zip", {
        status: 200,
        headers: {
          "Content-Disposition": 'attachment; filename="artifacts.zip"',
        },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await workspaceApi.downloadArtifacts("chat-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/user/workspace/artifacts/download?session_id=chat-1",
      {
        method: "GET",
        headers: { Authorization: "Bearer test-token" },
      },
    );
    expect(result.filename).toBe("artifacts.zip");
    expect(await result.blob.text()).toBe("zip");
  });

  it("downloads a single artifact with path segments encoded", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response("pptx", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await workspaceApi.downloadFile(
      "slides/深兆.pptx",
      "chat-1",
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/user/workspace/files/download/slides/%E6%B7%B1%E5%85%86.pptx?chatId=chat-1",
      {
        method: "GET",
        headers: { Authorization: "Bearer test-token" },
      },
    );
    expect(result.filename).toBe("深兆.pptx");
  });
});
