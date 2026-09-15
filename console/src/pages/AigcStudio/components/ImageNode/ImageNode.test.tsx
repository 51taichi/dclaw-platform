import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { ImageNode } from "./ImageNode";
import type { ImageNodeWorkflow } from "./types";

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

const workflow: ImageNodeWorkflow = {
  handleImageUpload: vi.fn(),
  handleImageToImageUpload: vi.fn(),
  handleImageUpscaleUpload: vi.fn(),
  handleImageComposerSubmit: vi.fn((node) => node),
  handleImageCaptureGroup: vi.fn(),
  handleGeneratedImageSendToImage: vi.fn(),
  handleGeneratedImageAnnotate: vi.fn(),
  handleGeneratedImageSetPrimary: vi.fn(),
  handleGeneratedImageToggleResults: vi.fn(),
  handleImageCaptureGroupSendToImage: vi.fn(),
  handleImageCaptureGroupSelect: vi.fn(),
  handleImageSlashCommand: vi.fn(),
};

const generatedImageNode: AigcCanvasNode = {
  id: "image-1",
  type: "image_generate",
  position: { x: 0, y: 0 },
  data: {
    title: "图片节点",
    imageState: "generated",
    outputs: [
      {
        id: "asset-1",
        kind: "image",
        name: "image_generate-result.jpg",
        path: "blob:generated-image",
        mime_type: "image/jpeg",
        created_at: "2026-06-23T00:00:00Z",
      },
    ],
  },
};

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;
const originalLocation = window.location;

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

describe("ImageNode", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    localStorage.removeItem("qwenpaw_auth_token");
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
    document
      .querySelectorAll("[data-aigc-download-link]")
      .forEach((element) => element.remove());
    restoreUrlObjectMethods();
  });

  it("shows generated images without rendering the asset file name as visible text", () => {
    render(
      <ImageNode
        node={generatedImageNode}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(screen.getByAltText("image_generate-result.jpg")).toHaveAttribute(
      "src",
      "blob:generated-image",
    );
    expect(
      screen.queryByText("image_generate-result.jpg"),
    ).not.toBeInTheDocument();
  });

  it("keeps successful batch images and shows a partial-success notice", () => {
    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            ...generatedImageNode.data,
            outputs: [
              {
                id: "asset-1",
                kind: "image",
                name: "first.jpg",
                path: "blob:first-image",
                mime_type: "image/jpeg",
                created_at: "2026-07-21T00:00:00Z",
                meta: {
                  image_count: 4,
                  partial_failure_count: 2,
                  partial_failure_errors: [
                    { image_index: 2, message: "WriteTimeout" },
                    {
                      image_index: 4,
                      message:
                        "The generated image was filtered by the safety policy.",
                    },
                  ],
                },
              },
              {
                id: "asset-3",
                kind: "image",
                name: "third.jpg",
                path: "blob:third-image",
                mime_type: "image/jpeg",
                created_at: "2026-07-21T00:00:00Z",
                meta: { image_count: 4, partial_failure_count: 2 },
              },
            ],
          },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    const notice = screen.getByTestId("aigc-image-partial-notice");
    expect(notice).toHaveTextContent("已生成 2/4 张");
    expect(notice).toHaveAttribute(
      "title",
      expect.stringContaining("filtered by the safety policy"),
    );
    expect(screen.queryByText("生成失败")).not.toBeInTheDocument();
  });

  it("keeps composer prompt text out of the image preview surface", () => {
    render(
      <ImageNode
        node={{
          id: "image-plain-text",
          type: "image_generate",
          position: { x: 0, y: 0 },
          data: {
            title: "图片节点",
            imageState: "editing",
            text: "输入框里的真实用户提示词",
            composerText: "输入框里的真实用户提示词",
          },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(
      screen.queryByText("输入框里的真实用户提示词"),
    ).not.toBeInTheDocument();
  });

  it("summarizes raw image generation errors in Chinese and keeps details available", () => {
    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            title: "图片节点",
            imageState: "failed",
            job_status: "failed",
            job_error:
              "HTTP 429 Too Many Requests: provider rate limit exceeded",
          },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(
      screen.getByText(
        "当前模型服务请求过多或额度不足，请稍后再试，或切换其他模型。",
      ),
    ).toBeInTheDocument();
    const details = screen.getByText("查看原始错误").closest("details");
    expect(details).toHaveTextContent(
      "HTTP 429 Too Many Requests: provider rate limit exceeded",
    );
  });

  it("identifies provider safety-policy failures instead of calling them timeouts", () => {
    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            title: "图片节点",
            imageState: "failed",
            job_status: "failed",
            job_error:
              "The generated image was filtered by the safety policy. Please adjust your prompt and try again.",
          },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(
      screen.getByText(
        "生成内容未通过模型安全策略，请调整提示词或参考图后重试。",
      ),
    ).toBeInTheDocument();
  });

  it("identifies MXAPI legal errors as content-review failures before generic 400 errors", () => {
    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            title: "图片节点",
            imageState: "failed",
            job_status: "failed",
            job_error:
              'GPT Image 请求失败: 400: submit failed: 451 {"error_code":"legal_error","message":"{}"}',
          },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(
      screen.getByText(
        "提示词被模型服务的内容审核拒绝，请调整可能引发误判的文案后重试。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "请求参数没有通过模型服务校验，请检查提示词、比例或参考图后重试。",
      ),
    ).not.toBeInTheDocument();
  });

  it("shows the selected primary image in compact multi-output results", () => {
    const generatedOutputs = Array.isArray(generatedImageNode.data.outputs)
      ? generatedImageNode.data.outputs
      : [];
    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            ...generatedImageNode.data,
            primaryOutputId: "asset-2",
            outputs: [
              ...generatedOutputs,
              {
                id: "asset-2",
                kind: "image",
                name: "selected-main.jpg",
                path: "blob:selected-main",
                mime_type: "image/jpeg",
                created_at: "2026-07-01T00:00:00Z",
              },
            ],
          },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(screen.getByAltText("selected-main.jpg")).toHaveAttribute(
      "src",
      "blob:selected-main",
    );
    expect(screen.getByTestId("aigc-image-result-stack")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "展开 2 张图片" }),
    ).toBeInTheDocument();
  });

  it("shows the multi-output expand control in the selected image toolbar", () => {
    const generatedOutputs = Array.isArray(generatedImageNode.data.outputs)
      ? generatedImageNode.data.outputs
      : [];
    const node = {
      ...generatedImageNode,
      data: {
        ...generatedImageNode.data,
        outputs: [
          ...generatedOutputs,
          {
            id: "asset-2",
            kind: "image",
            name: "second-result.jpg",
            path: "blob:second-result",
            mime_type: "image/jpeg",
            created_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    };

    render(<ImageNode node={node} selected t={t} workflow={workflow} />);

    const toolbar = screen.getByTestId("aigc-image-viewer-toolbar");
    const expandButton = within(toolbar).getByRole("button", {
      name: "展开 2 张图片",
    });

    expect(expandButton).toHaveTextContent("2张");
    fireEvent.click(expandButton);

    expect(workflow.handleGeneratedImageToggleResults).toHaveBeenCalledWith(
      node,
      true,
    );
  });

  it("expands multi-output results and lets users choose the main image", () => {
    const generatedOutputs = Array.isArray(generatedImageNode.data.outputs)
      ? generatedImageNode.data.outputs
      : [];
    const node = {
      ...generatedImageNode,
      data: {
        ...generatedImageNode.data,
        imageResultsExpanded: true,
        primaryOutputId: "asset-2",
        outputs: [
          ...generatedOutputs,
          {
            id: "asset-2",
            kind: "image",
            name: "selected-main.jpg",
            path: "blob:selected-main",
            mime_type: "image/jpeg",
            created_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    };

    render(<ImageNode node={node} selected t={t} workflow={workflow} />);

    const primaryPreview = screen.getByTestId("aigc-image-primary-preview");
    const sideGallery = screen.getByTestId("aigc-image-result-side-gallery");

    expect(
      within(primaryPreview).getByAltText("selected-main.jpg"),
    ).toHaveAttribute("src", "blob:selected-main");
    expect(
      within(sideGallery).getByAltText("image_generate-result.jpg"),
    ).toHaveAttribute("src", "blob:generated-image");
    expect(primaryPreview).not.toContainElement(sideGallery);

    fireEvent.click(
      screen.getByRole("button", {
        name: "设为主图 image_generate-result.jpg",
      }),
    );

    expect(workflow.handleGeneratedImageSetPrimary).toHaveBeenCalledWith(
      node,
      "asset-1",
    );
    expect(
      within(screen.getByTestId("aigc-image-viewer-toolbar")).getByRole(
        "button",
        { name: "收起图片结果" },
      ),
    ).toBeInTheDocument();
  });

  it("allows expanded result galleries to escape the image surface clipping", async () => {
    const css = await readFile(
      resolve(process.cwd(), "src/pages/AigcStudio/index.module.less"),
      "utf8",
    );

    expect(css).toMatch(
      /\.imageEditorSurface\[data-image-expanded="true"\]\s*{(?=[\s\S]*\boverflow: visible;)[\s\S]*}/,
    );
  });

  it("aligns the expanded image composer to the primary image edge", async () => {
    const css = await readFile(
      resolve(process.cwd(), "src/pages/AigcStudio/index.module.less"),
      "utf8",
    );

    expect(css).toMatch(
      /\.nodeImageCanvas\[data-image-results-expanded="true"\]\s+\.imageComposer\s*{(?=[\s\S]*\bleft:\s*0;)(?=[\s\S]*\bwidth:\s*var\(--aigc-image-primary-width,\s*100%\);)(?=[\s\S]*\bmax-width:\s*none;)(?=[\s\S]*\btransform:\s*none;)[\s\S]*}/,
    );
  });

  it("renders all four generated images when expanded", () => {
    const node = {
      ...generatedImageNode,
      data: {
        ...generatedImageNode.data,
        imageResultsExpanded: true,
        outputs: [
          {
            id: "asset-1",
            kind: "image",
            name: "result-1.jpg",
            path: "blob:result-1",
            mime_type: "image/jpeg",
            created_at: "2026-07-07T00:00:00Z",
          },
          {
            id: "asset-2",
            kind: "image",
            name: "result-2.jpg",
            path: "blob:result-2",
            mime_type: "image/jpeg",
            created_at: "2026-07-07T00:00:00Z",
          },
          {
            id: "asset-3",
            kind: "image",
            name: "result-3.jpg",
            path: "blob:result-3",
            mime_type: "image/jpeg",
            created_at: "2026-07-07T00:00:00Z",
          },
          {
            id: "asset-4",
            kind: "image",
            name: "result-4.jpg",
            path: "blob:result-4",
            mime_type: "image/jpeg",
            created_at: "2026-07-07T00:00:00Z",
          },
        ],
      },
    };

    render(<ImageNode node={node} selected t={t} workflow={workflow} />);

    const primaryPreview = screen.getByTestId("aigc-image-primary-preview");
    const sideGallery = screen.getByTestId("aigc-image-result-side-gallery");

    expect(within(primaryPreview).getByAltText("result-1.jpg")).toHaveAttribute(
      "src",
      "blob:result-1",
    );
    expect(sideGallery.querySelectorAll("figure")).toHaveLength(3);
    expect(within(sideGallery).getByAltText("result-2.jpg")).toHaveAttribute(
      "src",
      "blob:result-2",
    );
    expect(within(sideGallery).getByAltText("result-3.jpg")).toHaveAttribute(
      "src",
      "blob:result-3",
    );
    expect(within(sideGallery).getByAltText("result-4.jpg")).toHaveAttribute(
      "src",
      "blob:result-4",
    );
  });

  it("shows generated image actions above the selected node and hides input-updated badges", () => {
    const { rerender } = render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: { ...generatedImageNode.data, inputUpdated: true },
        }}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    expect(
      screen.queryByTestId("aigc-image-viewer-toolbar"),
    ).not.toBeInTheDocument();

    rerender(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: { ...generatedImageNode.data, inputUpdated: true },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const toolbar = screen.getByTestId("aigc-image-viewer-toolbar");
    const editor = screen.getByTestId("aigc-image-editor");
    expect(toolbar).toHaveAttribute("data-toolbar-placement", "node-above");
    expect(editor).not.toContainElement(toolbar);
    expect(
      screen.getByRole("button", { name: "下载结果" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "标注" })).toBeInTheDocument();
    expect(screen.queryByText("输入已更新")).not.toBeInTheDocument();
  });

  it("opens the annotation business from the generated image toolbar", () => {
    render(
      <ImageNode
        node={generatedImageNode}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "标注" }));

    expect(workflow.handleGeneratedImageAnnotate).toHaveBeenCalledWith(
      generatedImageNode,
    );
  });

  it("opens generated image preview as a page-level dialog", () => {
    render(
      <ImageNode
        node={generatedImageNode}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const editor = screen.getByTestId("aigc-image-editor");
    fireEvent.click(screen.getByRole("button", { name: "全屏查看" }));

    const previewDialog = screen.getByRole("dialog", { name: "图片预览" });
    expect(previewDialog).toBeInTheDocument();
    expect(document.body).toContainElement(previewDialog);
    expect(editor).not.toContainElement(previewDialog);
    expect(screen.getByTestId("aigc-image-result-preview")).toBe(previewDialog);
  });

  it("keeps the generated image preview inside a bounded dialog viewport", async () => {
    render(
      <ImageNode
        node={generatedImageNode}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "全屏查看" }));

    const previewDialog = screen.getByRole("dialog", { name: "图片预览" });
    const previewViewport = screen.getByTestId(
      "aigc-image-result-preview-viewport",
    );
    const previewImage = within(previewViewport).getByAltText(
      "image_generate-result.jpg",
    );
    expect(previewDialog).toContainElement(previewViewport);
    expect(previewViewport).toContainElement(previewImage);

    const css = await readFile(
      resolve(process.cwd(), "src/pages/AigcStudio/index.module.less"),
      "utf8",
    );
    expect(css).toMatch(
      /\.imageResultFullscreenViewport\s*{(?=[\s\S]*\boverflow: hidden;)[\s\S]*}/,
    );
    expect(css).toMatch(
      /\.imageResultFullscreenImage\s*{(?=[\s\S]*\bwidth: auto;)(?=[\s\S]*\bheight: auto;)(?=[\s\S]*\bmax-inline-size: 100%;)(?=[\s\S]*\bmax-block-size: 100%;)[\s\S]*}/,
    );
  });

  it("keeps generated size outside the image surface and does not show download status", async () => {
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    render(
      <ImageNode
        node={generatedImageNode}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const editor = screen.getByTestId("aigc-image-editor");
    expect(screen.getByTestId("aigc-image-node-meta")).toHaveTextContent(
      "1024 × 1024",
    );
    expect(editor).not.toHaveTextContent("1024 × 1024");

    fireEvent.click(screen.getByRole("button", { name: "下载结果" }));

    await waitFor(() => {
      expect(anchorClick).toHaveBeenCalled();
    });
    expect(
      screen.queryByTestId("aigc-image-node-download-status"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("已准备下载")).not.toBeInTheDocument();
    expect(editor).not.toHaveTextContent("已准备下载");
  });

  it("keeps download toolbar pointer events from reaching the canvas node shell", () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    const parentMouseDown = vi.fn();
    const parentPointerDown = vi.fn();
    const parentClick = vi.fn();

    render(
      <div
        onMouseDown={parentMouseDown}
        onPointerDown={parentPointerDown}
        onClick={parentClick}
      >
        <ImageNode
          node={generatedImageNode}
          selected
          t={t}
          workflow={workflow}
        />
      </div>,
    );

    const downloadButton = screen.getByRole("button", { name: "下载结果" });
    fireEvent.pointerDown(downloadButton);
    fireEvent.mouseDown(downloadButton);
    fireEvent.click(downloadButton);

    expect(parentPointerDown).not.toHaveBeenCalled();
    expect(parentMouseDown).not.toHaveBeenCalled();
    expect(parentClick).not.toHaveBeenCalled();
  });

  it("updates generated image size from the loaded image dimensions", async () => {
    render(
      <ImageNode
        node={generatedImageNode}
        selected={false}
        t={t}
        workflow={workflow}
      />,
    );

    const image = screen.getByAltText("image_generate-result.jpg");
    Object.defineProperty(image, "naturalWidth", {
      configurable: true,
      value: 1536,
    });
    Object.defineProperty(image, "naturalHeight", {
      configurable: true,
      value: 864,
    });
    fireEvent.load(image);

    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-node-meta")).toHaveTextContent(
        "1536 × 864",
      );
    });
  });

  it("keeps authenticated download links alive until the browser starts the download", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi
        .fn()
        .mockResolvedValue(
          new Blob(["generated image"], { type: "image/jpeg" }),
        ),
    });
    const createObjectUrl = vi.fn(() => "blob:downloaded-generated-image");
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
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            ...generatedImageNode.data,
            outputs: [
              {
                id: "asset-1",
                kind: "image",
                name: "image_generate-result.jpg",
                path: "/api/user/aigc-studio/assets/asset-1/file",
                mime_type: "image/jpeg",
                created_at: "2026-06-23T00:00:00Z",
              },
            ],
          },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下载结果" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:3000/api/user/aigc-studio/assets/asset-1/file",
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    const anchor = document.querySelector(
      "a[download='image_generate-result.jpg']",
    );
    expect(anchor).toBeInTheDocument();
    expect(anchor).toHaveAttribute("href", "blob:downloaded-generated-image");
    expect(revokeObjectUrl).not.toHaveBeenCalled();
    expect(screen.queryByText("已准备下载")).not.toBeInTheDocument();
  });

  it("refreshes expired OSS generated image urls through the asset API before downloading", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi
        .fn()
        .mockResolvedValue(
          new Blob(["generated image"], { type: "image/jpeg" }),
        ),
    });
    const createObjectUrl = vi.fn(() => "blob:downloaded-generated-image");
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });

    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            ...generatedImageNode.data,
            outputs: [
              {
                id: "asset-oss-1",
                kind: "image",
                name: "image_generate-result.jpg",
                path: "oss://qwenpaw-aigc/aigc/generated/asset-oss-1.jpg",
                url: "https://oss.example.test/aigc/generated/asset-oss-1.jpg?Expires=1&Signature=expired",
                mime_type: "image/jpeg",
                created_at: "2026-06-23T00:00:00Z",
              },
            ],
          },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下载结果" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:3000/api/user/aigc-studio/assets/asset-oss-1/file",
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(
      document.querySelector("a[download='image_generate-result.jpg']"),
    ).toHaveAttribute("href", "blob:downloaded-generated-image");
  });

  it("downloads same-host http API assets through the current https origin", async () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("https://dclaw.deepmega.cn/aigc-studio"),
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi
        .fn()
        .mockResolvedValue(
          new Blob(["generated image"], { type: "image/jpeg" }),
        ),
    });
    const createObjectUrl = vi.fn(() => "blob:downloaded-generated-image");
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });

    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            ...generatedImageNode.data,
            outputs: [
              {
                id: "asset-1",
                kind: "image",
                name: "image_generate-result.jpg",
                url: "http://dclaw.deepmega.cn/api/user/aigc-studio/assets/asset-1/file",
                mime_type: "image/jpeg",
                created_at: "2026-06-23T00:00:00Z",
              },
            ],
          },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下载结果" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "https://dclaw.deepmega.cn/api/user/aigc-studio/assets/asset-1/file",
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
  });

  it("downloads from the already rendered authenticated image blob", async () => {
    localStorage.setItem("qwenpaw_auth_token", "token-1");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi
        .fn()
        .mockResolvedValue(
          new Blob(["rendered image"], { type: "image/jpeg" }),
        ),
    });
    const createObjectUrl = vi.fn(() => "blob:rendered-generated-image");
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });

    render(
      <ImageNode
        node={{
          ...generatedImageNode,
          data: {
            ...generatedImageNode.data,
            outputs: [
              {
                id: "asset-1",
                kind: "image",
                name: "image_generate-result.jpg",
                path: "/api/user/aigc-studio/assets/asset-1/file",
                mime_type: "image/jpeg",
                created_at: "2026-06-23T00:00:00Z",
              },
            ],
          },
        }}
        selected
        t={t}
        workflow={workflow}
      />,
    );

    const image = await screen.findByAltText("image_generate-result.jpg");
    await waitFor(() => {
      expect(image).toHaveAttribute("src", "blob:rendered-generated-image");
    });
    fireEvent.load(image);
    fetchMock.mockClear();
    createObjectUrl.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "下载结果" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(createObjectUrl).not.toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(
      document.querySelector("a[download='image_generate-result.jpg']"),
    ).toHaveAttribute("href", "blob:rendered-generated-image");
  });
});
