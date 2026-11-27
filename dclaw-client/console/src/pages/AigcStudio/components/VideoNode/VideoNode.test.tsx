import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { clearAuthenticatedAssetImageCache } from "../AuthenticatedAssetImage";
import { VideoNode } from "./VideoNode";
import type { VideoNodeWorkflow } from "./types";

const t = ((
  _key: string,
  fallback?: string,
  values?: Record<string, unknown>,
) => {
  const template = fallback ?? _key;
  return Object.entries(values ?? {}).reduce(
    (result, [key, value]) => result.replace(`{{${key}}}`, String(value)),
    template,
  );
}) as never;

const workflow: VideoNodeWorkflow = {
  handleVideoUpload: vi.fn(),
  handleVideoTryUpload: vi.fn(),
  handleVideoReferenceUpload: vi.fn(),
  handleGeneratedVideoAction: vi.fn(),
  handleVideoCancelGeneration: vi.fn(),
  handleVideoRetryGeneration: vi.fn(),
  handleVideoComposerSubmit: vi.fn((node) => node),
};

const generatedVideoNode: AigcCanvasNode = {
  id: "video-1",
  type: "video_generate",
  position: { x: 0, y: 0 },
  data: {
    title: "视频节点",
    aspectRatio: "16:9",
    videoDuration: 5,
    videoResolution: "720P",
    outputs: [
      {
        id: "asset-video-1",
        kind: "video",
        name: "generated-video.mp4",
        path: "aigc_studio/canvas-1/job-1/generated-video.mp4",
        url: "/api/user/aigc-studio/assets/asset-video-1/file",
        mime_type: "video/mp4",
        width: 1280,
        height: 720,
      },
    ],
  },
};

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

const restoreUrlObjectMethods = () => {
  if (originalCreateObjectUrl) {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: originalCreateObjectUrl,
    });
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectUrl) {
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectUrl,
    });
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
  }
};

describe("VideoNode", () => {
  beforeEach(() => {
    localStorage.setItem("qwenpaw_auth_token", "test-token");
    clearAuthenticatedAssetImageCache();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              url: "https://static.example.test/aigc/generated/video-1.mp4?signature=1",
              expires_in: 900,
            }),
            { headers: { "content-type": "application/json" } },
          ),
      ),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    localStorage.removeItem("qwenpaw_auth_token");
    document
      .querySelectorAll("[data-aigc-download-link]")
      .forEach((element) => element.remove());
    restoreUrlObjectMethods();
    clearAuthenticatedAssetImageCache();
  });

  it("loads generated protected video assets through authenticated media", async () => {
    render(
      <VideoNode
        node={generatedVideoNode}
        selected={true}
        t={t}
        workflow={workflow}
      />,
    );

    const editor = screen.getByTestId("aigc-video-editor");
    const preview = screen.getByTestId("aigc-video-result-preview");

    expect(editor).toHaveAttribute("data-video-state", "generated");
    expect(editor).toHaveAttribute("data-video-aspect-ratio", "16:9");
    expect(preview).toHaveAttribute("data-authenticated-asset", "true");
    expect(preview).toHaveStyle({ objectFit: "contain" });
    expect(editor).not.toHaveTextContent(
      "/api/user/aigc-studio/assets/asset-video-1/file",
    );

    await waitFor(() =>
      expect(preview).toHaveAttribute(
        "src",
        "https://static.example.test/aigc/generated/video-1.mp4?signature=1",
      ),
    );
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:3000/api/user/aigc-studio/assets/asset-video-1/signed-url",
      {
        credentials: "include",
        headers: { Authorization: "Bearer test-token" },
      },
    );
  });

  it("shows the real portrait dimensions reported by the generated video", () => {
    render(
      <VideoNode
        node={{
          ...generatedVideoNode,
          data: {
            ...generatedVideoNode.data,
            aspectRatio: "9:16",
            outputs: [
              {
                id: "asset-video-portrait",
                kind: "video",
                name: "generated-portrait-video.mp4",
                path: "aigc_studio/canvas-1/job-portrait/generated-video.mp4",
                url: "/api/user/aigc-studio/assets/asset-video-portrait/file",
                mime_type: "video/mp4",
              },
            ],
          },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const preview = screen.getByTestId("aigc-video-result-preview");
    Object.defineProperty(preview, "videoWidth", {
      configurable: true,
      value: 720,
    });
    Object.defineProperty(preview, "videoHeight", {
      configurable: true,
      value: 1280,
    });
    fireEvent.loadedMetadata(preview);

    expect(screen.getByTestId("aigc-video-editor")).toHaveAttribute(
      "data-video-aspect-ratio",
      "9:16",
    );
    expect(screen.getByText("720 × 1280")).toBeInTheDocument();
  });

  it("shows generated video actions above the selected node", () => {
    const { rerender } = render(
      <VideoNode
        node={generatedVideoNode}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(
      screen.queryByTestId("aigc-video-viewer-toolbar"),
    ).not.toBeInTheDocument();

    rerender(
      <VideoNode
        node={generatedVideoNode}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const toolbar = screen.getByTestId("aigc-video-viewer-toolbar");
    const editor = screen.getByTestId("aigc-video-editor");
    expect(toolbar).toHaveAttribute("data-toolbar-placement", "node-above");
    expect(editor).not.toContainElement(toolbar);
    expect(
      screen.getByRole("button", { name: "下载视频" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "全屏查看视频" }),
    ).toBeInTheDocument();
  });

  it("downloads generated protected videos without opening the preview surface", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/signed-url")) {
        return new Response(
          JSON.stringify({
            url: "https://static.example.test/aigc/generated/video-1.mp4?signature=1",
            expires_in: 900,
          }),
          { headers: { "content-type": "application/json" } },
        );
      }
      return new Response(new Blob(["generated video"], { type: "video/mp4" }));
    });
    const createObjectUrl = vi.fn(() => "blob:downloaded-generated-video");
    const revokeObjectUrl = vi.fn();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrl,
    });

    render(
      <VideoNode
        node={generatedVideoNode}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const editor = screen.getByTestId("aigc-video-editor");
    fireEvent.click(screen.getByRole("button", { name: "下载视频" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:3000/api/user/aigc-studio/assets/asset-video-1/file",
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    const anchor = document.querySelector("a[download='generated-video.mp4']");
    expect(anchor).toBeInTheDocument();
    expect(anchor).toHaveAttribute("href", "blob:downloaded-generated-video");
    expect(screen.queryByText("已准备下载")).not.toBeInTheDocument();
    expect(editor).not.toHaveTextContent("已准备下载");
    expect(
      screen.queryByRole("dialog", { name: "视频预览" }),
    ).not.toBeInTheDocument();
    expect(revokeObjectUrl).not.toHaveBeenCalled();
  });

  it("downloads generated direct video assets through the asset API instead of navigating to preview", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi
        .fn()
        .mockResolvedValue(
          new Blob(["generated video"], { type: "video/mp4" }),
        ),
    });
    const createObjectUrl = vi.fn(() => "blob:downloaded-direct-video");
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });

    render(
      <VideoNode
        node={{
          ...generatedVideoNode,
          data: {
            ...generatedVideoNode.data,
            outputs: [
              {
                id: "asset-video-1",
                kind: "video",
                name: "generated-video.mp4",
                url: "https://static.example.test/aigc/generated/video-1.mp4?signature=1",
                mime_type: "video/mp4",
                width: 1280,
                height: 720,
              },
            ],
          },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下载视频" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:3000/api/user/aigc-studio/assets/asset-video-1/file",
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(
      document.querySelector("a[download='generated-video.mp4']"),
    ).toHaveAttribute("href", "blob:downloaded-direct-video");
    expect(
      screen.queryByRole("dialog", { name: "视频预览" }),
    ).not.toBeInTheDocument();
  });
});
