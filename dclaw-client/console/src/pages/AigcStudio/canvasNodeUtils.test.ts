import { describe, expect, it } from "vitest";

import type { AigcCanvasNode, AigcAsset } from "../../api/modules/aigcStudio";
import {
  assetKindFromFile,
  assetPreviewSource,
  assetPreviewKind,
  canvasAssetFromNode,
  nodeOutputs,
  nodePrimaryOutputName,
  nodePrimaryOutputPreviewSource,
  nodeVisualHeight,
  nodeVisualWidth,
  shouldRenderNodeOutputList,
  translatedCapability,
  translatedNodeType,
} from "./canvasNodeUtils";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("canvasNodeUtils", () => {
  it("translates node and capability fallbacks", () => {
    expect(translatedNodeType(t, "video_generate")).toBe("视频生成");
    expect(translatedCapability(t, "text_to_audio")).toBe("文生音频");
    expect(translatedNodeType(t, "custom_node")).toBe("custom_node");
  });

  it("computes visual dimensions for generated and uploaded nodes", () => {
    const uploadedSource: AigcCanvasNode = {
      id: "asset-1",
      type: "reference_asset",
      position: { x: 0, y: 0 },
      data: {
        previewKind: "uploaded_source",
      },
    };
    const fullscreenScript: AigcCanvasNode = {
      id: "script-1",
      type: "script_generate",
      position: { x: 0, y: 0 },
      data: {
        scriptFullscreen: true,
      },
    };
    const squareUploadedSource: AigcCanvasNode = {
      ...uploadedSource,
      data: {
        ...uploadedSource.data,
        assetWidth: 1080,
        assetHeight: 1080,
      },
    };
    const portraitUploadedSource: AigcCanvasNode = {
      ...uploadedSource,
      data: {
        ...uploadedSource.data,
        assetWidth: 1296,
        assetHeight: 3024,
      },
    };
    const longImageExportNode: AigcCanvasNode = {
      id: "long-1",
      type: "long_image_export",
      position: { x: 0, y: 0 },
      data: {},
    };

    expect(nodeVisualWidth(uploadedSource)).toBe(280);
    expect(nodeVisualHeight(uploadedSource)).toBe(420);
    expect(nodeVisualWidth(squareUploadedSource)).toBe(360);
    expect(nodeVisualHeight(squareUploadedSource)).toBe(360);
    expect(nodeVisualWidth(portraitUploadedSource)).toBe(154);
    expect(nodeVisualHeight(portraitUploadedSource)).toBe(360);
    expect(nodeVisualWidth(fullscreenScript)).toBe(1600);
    expect(nodeVisualHeight(fullscreenScript)).toBe(760);
    expect(nodeVisualWidth(longImageExportNode)).toBe(420);
    expect(nodeVisualHeight(longImageExportNode)).toBe(160);
  });

  it("lets draft image nodes follow the selected ratio and locks generated nodes to output ratio", () => {
    const draftNode: AigcCanvasNode = {
      id: "image-draft",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        aspectRatio: "9:16",
      },
    };
    const generatedNode: AigcCanvasNode = {
      id: "image-generated",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        imageState: "generated",
        aspectRatio: "16:9",
        outputs: [
          {
            id: "asset-1",
            kind: "image",
            name: "square.png",
            path: "/api/user/aigc-studio/assets/asset-1/file",
            mime_type: "image/png",
            width: 2048,
            height: 2048,
            created_at: "2026-06-23T00:00:00Z",
          },
        ],
      },
    };
    const generatedNodeWithSavedRatio: AigcCanvasNode = {
      ...generatedNode,
      id: "image-generated-meta",
      data: {
        imageState: "generated",
        aspectRatio: "1:1",
        outputs: [
          {
            id: "asset-2",
            kind: "image",
            name: "portrait.png",
            path: "/api/user/aigc-studio/assets/asset-2/file",
            mime_type: "image/png",
            created_at: "2026-06-23T00:00:00Z",
            meta: {
              parameters: {
                aspectRatio: "9:16",
              },
            },
          },
        ],
      },
    };
    const generatedNodeWithNodeRatio: AigcCanvasNode = {
      ...generatedNode,
      id: "image-generated-node-ratio",
      data: {
        imageState: "generated",
        aspectRatio: "16:9",
        generatedAspectRatio: "3:4",
        outputs: [
          {
            id: "asset-3",
            kind: "image",
            name: "portrait.png",
            path: "/api/user/aigc-studio/assets/asset-3/file",
            mime_type: "image/png",
            created_at: "2026-06-23T00:00:00Z",
          },
        ],
      },
    };

    expect(nodeVisualHeight(draftNode)).toBeGreaterThan(
      nodeVisualWidth(draftNode),
    );
    expect(nodeVisualWidth(generatedNode)).toBe(
      nodeVisualHeight(generatedNode),
    );
    expect(nodeVisualHeight(generatedNodeWithSavedRatio)).toBeGreaterThan(
      nodeVisualWidth(generatedNodeWithSavedRatio),
    );
    expect(nodeVisualHeight(generatedNodeWithNodeRatio)).toBeGreaterThan(
      nodeVisualWidth(generatedNodeWithNodeRatio),
    );
  });

  it("uses a portrait frame only for 9:16 video and a landscape frame otherwise", () => {
    const portraitDraft: AigcCanvasNode = {
      id: "video-portrait-draft",
      type: "video_generate",
      position: { x: 0, y: 0 },
      data: { aspectRatio: "9:16" },
    };
    const landscapeRatios = ["16:9", "1:1", "4:3", "3:4", "21:9", "Auto"];
    const generatedPortrait: AigcCanvasNode = {
      ...portraitDraft,
      id: "video-generated-portrait",
      data: {
        videoState: "generated",
        aspectRatio: "16:9",
        generatedAspectRatio: "9:16",
        outputs: [
          {
            id: "video-output",
            kind: "video",
            name: "portrait.mp4",
            path: "/api/user/aigc-studio/assets/video-output/file",
            width: 720,
            height: 1280,
            created_at: "2026-07-21T00:00:00Z",
          },
        ],
      },
    };

    expect(nodeVisualWidth(portraitDraft)).toBe(371);
    expect(nodeVisualHeight(portraitDraft)).toBe(660);
    landscapeRatios.forEach((aspectRatio) => {
      const node = {
        ...portraitDraft,
        id: `video-${aspectRatio}`,
        data: { aspectRatio },
      };
      expect(nodeVisualWidth(node)).toBe(660);
      expect(nodeVisualHeight(node)).toBe(371);
    });
    expect(nodeVisualWidth(generatedPortrait)).toBe(371);
    expect(nodeVisualHeight(generatedPortrait)).toBe(660);
  });

  it("keeps expanded multi-image results out of node layout dimensions", () => {
    const outputs: AigcAsset[] = [
      "asset-1",
      "asset-2",
      "asset-3",
      "asset-4",
    ].map((id) => ({
      id,
      kind: "image",
      name: `${id}.png`,
      path: `/api/user/aigc-studio/assets/${id}/file`,
      mime_type: "image/png",
      created_at: "2026-07-01T00:00:00Z",
      meta: {
        parameters: {
          aspectRatio: "16:9",
        },
      },
    }));
    const collapsedNode: AigcCanvasNode = {
      id: "image-multi",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        imageState: "generated",
        aspectRatio: "16:9",
        outputs,
      },
    };
    const expandedNode: AigcCanvasNode = {
      ...collapsedNode,
      data: {
        ...collapsedNode.data,
        imageResultsExpanded: true,
      },
    };

    expect(nodeVisualWidth(expandedNode)).toBe(nodeVisualWidth(collapsedNode));
    expect(nodeVisualHeight(expandedNode)).toBe(
      nodeVisualHeight(collapsedNode),
    );
  });

  it("classifies uploaded file kinds and preview kinds", () => {
    expect(
      assetKindFromFile(new File(["video"], "clip.mp4", { type: "video/mp4" })),
    ).toBe("video");
    expect(
      assetKindFromFile(
        new File(["audio"], "music.wav", { type: "audio/wav" }),
      ),
    ).toBe("audio");
    expect(
      assetKindFromFile(
        new File(["image"], "frame.png", { type: "image/png" }),
      ),
    ).toBe("image");
    expect(assetPreviewKind("video")).toBe("uploaded_video");
    expect(assetPreviewKind("audio")).toBe("audio_source");
    expect(assetPreviewKind("image")).toBe("uploaded_source");
  });

  it("reads node output arrays safely", () => {
    const output: AigcAsset = {
      id: "asset-1",
      kind: "image",
      name: "frame.png",
      path: "aigc/frame.png",
      mime_type: "image/png",
      created_at: "2026-06-12T00:00:00Z",
    };
    const node: AigcCanvasNode = {
      id: "image-1",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        outputs: [output],
      },
    };

    expect(nodeOutputs(node)).toEqual([output]);
    expect(nodeOutputs({ ...node, data: {} })).toEqual([]);
  });

  it("uses the selected primary generated output when reading node previews", () => {
    const node: AigcCanvasNode = {
      id: "image-1",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        primaryOutputId: "asset-2",
        outputs: [
          {
            id: "asset-1",
            kind: "image",
            name: "first.png",
            path: "/api/user/aigc-studio/assets/asset-1/file",
            mime_type: "image/png",
            created_at: "2026-07-01T00:00:00Z",
          },
          {
            id: "asset-2",
            kind: "image",
            name: "main.png",
            path: "/api/user/aigc-studio/assets/asset-2/file",
            mime_type: "image/png",
            created_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    };

    expect(nodePrimaryOutputName(node)).toBe("main.png");
    expect(nodePrimaryOutputPreviewSource(node)).toBe(
      "/api/user/aigc-studio/assets/asset-2/file",
    );
  });

  it("keeps node-owned outputs inside specialized node surfaces", () => {
    const output: AigcAsset = {
      id: "asset-1",
      kind: "image",
      name: "frame.png",
      path: "blob:frame",
      mime_type: "image/png",
      created_at: "2026-06-23T00:00:00Z",
    };
    const imageNode: AigcCanvasNode = {
      id: "image-1",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: { outputs: [output] },
    };
    const videoNode: AigcCanvasNode = {
      ...imageNode,
      id: "video-1",
      type: "video_generate",
    };
    const promptNode: AigcCanvasNode = {
      ...imageNode,
      id: "prompt-1",
      type: "prompt",
      data: {
        textState: "generated",
        text: "生成后的文本内容",
        outputs: [
          {
            id: "text-asset-1",
            kind: "file",
            name: "prompt-1.txt",
            path: "aigc_studio/canvas-1/job-text/prompt-1.txt",
            url: "/api/user/aigc-studio/assets/text-asset-1/file",
            mime_type: "text/plain",
            created_at: "2026-06-23T00:00:00Z",
            meta: { text: "生成后的文本内容" },
          },
        ],
      },
    };
    const scriptNode: AigcCanvasNode = {
      ...promptNode,
      id: "script-1",
      type: "script_generate",
    };

    expect(shouldRenderNodeOutputList(imageNode)).toBe(false);
    expect(shouldRenderNodeOutputList(promptNode)).toBe(false);
    expect(shouldRenderNodeOutputList(scriptNode)).toBe(false);
    expect(shouldRenderNodeOutputList(videoNode)).toBe(false);
  });

  it("prefers browser-ready asset urls and ignores workspace-relative paths", () => {
    expect(
      assetPreviewSource({
        url: " https://assets.test/image.png ",
        path: "aigc_studio/canvas-1/job-2/image-1.svg",
      }),
    ).toBe("https://assets.test/image.png");
    expect(
      assetPreviewSource({ path: "/api/user/aigc-studio/assets/asset-1/file" }),
    ).toBe("/api/user/aigc-studio/assets/asset-1/file");
    expect(assetPreviewSource({ path: "blob:test" })).toBe("blob:test");
    expect(
      assetPreviewSource({ path: "aigc_studio/canvas-1/job-2/image-1.svg" }),
    ).toBeUndefined();
  });

  it("uses generated output URLs when saving an image node into the asset library", () => {
    const generatedNode: AigcCanvasNode = {
      id: "image-generated",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        title: "生成海报",
        text: "高端品牌海报",
        savedToAssets: true,
        savedAt: 36,
        outputs: [
          {
            id: "asset-1",
            kind: "image",
            name: "poster.png",
            path: "/api/user/aigc-studio/assets/asset-1/file",
            mime_type: "image/png",
            created_at: "2026-06-23T00:00:00Z",
          },
        ],
      },
    };

    expect(canvasAssetFromNode(t, generatedNode, "素材")).toMatchObject({
      title: "生成海报",
      text: "高端品牌海报",
      assetPreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
    });
  });
});
