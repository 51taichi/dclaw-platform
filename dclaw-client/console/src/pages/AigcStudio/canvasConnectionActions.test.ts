import { describe, expect, it } from "vitest";

import type { AigcCanvas, AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  applyPortConnectionToCanvas,
  applyPortDisconnectionToCanvas,
  cleanTargetDataForRemovedEdges,
  reconcileCanvasConnectionData,
} from "./canvasConnectionActions";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const referenceNode: AigcCanvasNode = {
  id: "asset-1",
  type: "reference_asset",
  position: { x: 80, y: 90 },
  data: {
    assetKind: "image",
    assetName: "portrait.png",
    assetPreviewUrl: "/api/user/aigc-studio/assets/portrait.png/file",
    previewKind: "uploaded_source",
  },
};

const promptNode: AigcCanvasNode = {
  id: "prompt-1",
  type: "prompt",
  position: { x: 80, y: 90 },
  data: {
    title: "文本节点",
    text: "你说的是什么",
  },
};

const imageNode: AigcCanvasNode = {
  id: "image-1",
  type: "image_generate",
  position: { x: 520, y: 100 },
  data: {
    title: "小女孩",
    text: "小女孩",
    imageState: "generated",
  },
};

const generatedSourceNode: AigcCanvasNode = {
  id: "image-source",
  type: "image_generate",
  position: { x: 80, y: 90 },
  data: {
    title: "上游生成图",
    text: "上游生成图",
    imageState: "generated",
    outputs: [
      {
        id: "source-output",
        kind: "image",
        name: "source-result.jpg",
        path: "aigc/source-result.jpg",
        url: "/api/user/aigc-studio/assets/source-output/file",
        created_at: "2026-06-24T00:00:00Z",
      },
    ],
  },
};

const longImageNode: AigcCanvasNode = {
  id: "long-1",
  type: "long_image_export",
  position: { x: 920, y: 120 },
  data: {
    title: "公众号长图",
  },
};

const styleTemplateNode: AigcCanvasNode = {
  id: "style-cgv2",
  type: "reference_asset",
  position: { x: 80, y: 420 },
  data: {
    assetRole: "style_template",
    assetKind: "image",
    assetName: "一键国漫CGV2",
    assetPreviewUrl: "/api/user/aigc-studio/styles/cgv2/cover",
    styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
    styleKeywords: "国漫 CG 风格",
    previewKind: "style_template",
  },
};

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [referenceNode, imageNode],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-23T00:00:00Z",
  updated_at: "2026-06-23T00:00:00Z",
});

describe("canvasConnectionActions", () => {
  it("connects a prompt node to an image node as an upstream prompt without filling the image input", () => {
    const emptyImageNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        title: "图片节点",
        imageState: "empty",
      },
    };
    const result = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [promptNode, emptyImageNode],
      },
      anchorNodeId: "prompt-1",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(result?.selectedNodeId).toBe("image-1");
    expect(result?.canvas.edges).toEqual([
      expect.objectContaining({
        id: "edge-prompt-1-image-1",
        source: "prompt-1",
        target: "image-1",
        sourceHandle: "right",
        targetHandle: "left",
        data: expect.objectContaining({ role: "prompt" }),
      }),
    ]);
    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      title: "图片节点",
      imageState: "empty",
      showTryOptions: false,
      inputUpdated: true,
    });
    expect(result?.canvas.nodes[1]?.data).not.toHaveProperty("text");
    expect(result?.canvas.nodes[1]?.data).not.toHaveProperty("composerText");
  });

  it("connects a right-port reference drag to an existing image node without replacing its prompt", () => {
    const result = applyPortConnectionToCanvas({
      canvas: canvasFixture(),
      anchorNodeId: "asset-1",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(result?.selectedNodeId).toBe("image-1");
    expect(result?.canvas.edges).toEqual([
      expect.objectContaining({
        id: "edge-asset-1-image-1",
        source: "asset-1",
        target: "image-1",
        sourceHandle: "right",
        targetHandle: "left",
        data: expect.objectContaining({ role: "reference_image" }),
      }),
    ]);
    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      title: "小女孩",
      text: "小女孩",
      imageState: "generated",
      imageMode: "image_to_image",
      referenceThumb: true,
      referenceAssetName: "portrait.png",
      referencePreviewUrl: "/api/user/aigc-studio/assets/portrait.png/file",
      inputUpdated: true,
    });
  });

  it("connects a left-port drag by treating the dropped node as upstream", () => {
    const result = applyPortConnectionToCanvas({
      canvas: canvasFixture(),
      anchorNodeId: "image-1",
      dropNodeId: "asset-1",
      side: "left",
      t,
    });

    expect(result?.canvas.edges[0]).toMatchObject({
      source: "asset-1",
      target: "image-1",
    });
  });

  it("rejects incompatible and duplicate connections", () => {
    const audioNode: AigcCanvasNode = {
      ...referenceNode,
      id: "audio-1",
      data: {
        assetKind: "audio",
        assetName: "beat.wav",
        assetPreviewUrl: "/api/user/aigc-studio/assets/beat.wav/file",
      },
    };
    const canvas = {
      ...canvasFixture(),
      nodes: [audioNode, imageNode],
    };

    expect(
      applyPortConnectionToCanvas({
        canvas,
        anchorNodeId: "audio-1",
        dropNodeId: "image-1",
        side: "right",
        t,
      }),
    ).toBeNull();

    const connected = applyPortConnectionToCanvas({
      canvas: canvasFixture(),
      anchorNodeId: "asset-1",
      dropNodeId: "image-1",
      side: "right",
      t,
    });
    const connectedAgain = applyPortConnectionToCanvas({
      canvas: connected!.canvas,
      anchorNodeId: "asset-1",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(connectedAgain?.canvas.edges).toHaveLength(1);
  });

  it("uses generated image output as the reference thumbnail when connecting two image nodes", () => {
    const result = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [generatedSourceNode, imageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(result?.canvas.edges[0]).toMatchObject({
      id: "edge-image-source-image-1",
      source: "image-source",
      target: "image-1",
      data: expect.objectContaining({ role: "reference_image" }),
    });
    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      imageMode: "image_to_image",
      referenceThumb: true,
      referenceAssetName: "source-result.jpg",
      referencePreviewUrl: "/api/user/aigc-studio/assets/source-output/file",
      inputUpdated: true,
    });
  });

  it("uses reference guidance as placeholder instead of editable image prompt text", () => {
    const emptyImageNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        title: "图片节点",
        imageState: "empty",
      },
    };

    const result = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [referenceNode, emptyImageNode],
      },
      anchorNodeId: "asset-1",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      imageMode: "image_to_image",
      referenceThumb: true,
      referenceAssetName: "portrait.png",
      referencePreviewUrl: "/api/user/aigc-studio/assets/portrait.png/file",
      composerPlaceholder: "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
      inputUpdated: true,
    });
    expect(result?.canvas.nodes[1]?.data).not.toHaveProperty("text");
    expect(result?.canvas.nodes[1]?.data).not.toHaveProperty("composerText");
  });

  it("uses first-frame guidance as placeholder instead of editable video prompt text", () => {
    const videoNode: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 520, y: 100 },
      data: {
        title: "视频节点",
        videoState: "empty",
      },
    };

    const result = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [referenceNode, videoNode],
      },
      anchorNodeId: "asset-1",
      dropNodeId: "video-1",
      side: "right",
      t,
    });

    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      activeVideoTab: "image_to_video",
      videoMode: "image_to_video",
      referenceThumb: true,
      referenceAssetName: "portrait.png",
      referencePreviewUrl: "/api/user/aigc-studio/assets/portrait.png/file",
      composerPlaceholder: "以当前图为首帧生成视频。",
      inputUpdated: true,
    });
    expect(result?.canvas.nodes[1]?.data).not.toHaveProperty("text");
    expect(result?.canvas.nodes[1]?.data).not.toHaveProperty("composerText");
  });

  it("connects prompt and image right-port drags to a long-image export node", () => {
    const promptResult = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [promptNode, longImageNode],
      },
      anchorNodeId: "prompt-1",
      dropNodeId: "long-1",
      side: "right",
      t,
    });

    expect(promptResult?.selectedNodeId).toBe("long-1");
    expect(promptResult?.canvas.edges[0]).toMatchObject({
      id: "edge-prompt-1-long-1",
      source: "prompt-1",
      target: "long-1",
      sourceHandle: "right",
      targetHandle: "left",
      data: expect.objectContaining({ role: "prompt" }),
    });
    expect(promptResult?.canvas.nodes[1]?.data).toMatchObject({
      title: "公众号长图",
      showTryOptions: false,
      inputUpdated: true,
    });
    expect(promptResult?.canvas.nodes[1]?.data).not.toHaveProperty("text");
    expect(promptResult?.canvas.nodes[1]?.data).not.toHaveProperty(
      "composerText",
    );

    const imageResult = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [generatedSourceNode, longImageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "long-1",
      side: "right",
      t,
    });

    expect(imageResult?.selectedNodeId).toBe("long-1");
    expect(imageResult?.canvas.edges[0]).toMatchObject({
      id: "edge-image-source-long-1",
      source: "image-source",
      target: "long-1",
      sourceHandle: "right",
      targetHandle: "left",
      data: expect.objectContaining({ role: "reference_image" }),
    });
    expect(imageResult?.canvas.nodes[1]?.data).toMatchObject({
      title: "公众号长图",
      showTryOptions: false,
      inputUpdated: true,
    });
    expect(imageResult?.canvas.nodes[1]?.data).not.toHaveProperty(
      "referenceThumb",
    );
    expect(imageResult?.canvas.nodes[1]?.data).not.toHaveProperty(
      "referenceAssetName",
    );
    expect(imageResult?.canvas.nodes[1]?.data).not.toHaveProperty(
      "referencePreviewUrl",
    );
  });

  it("uses the selected primary generated output when connecting image nodes", () => {
    const sourceOutputs = Array.isArray(generatedSourceNode.data.outputs)
      ? generatedSourceNode.data.outputs
      : [];
    const sourceWithPrimary: AigcCanvasNode = {
      ...generatedSourceNode,
      data: {
        ...generatedSourceNode.data,
        primaryOutputId: "source-output-2",
        outputs: [
          ...sourceOutputs,
          {
            id: "source-output-2",
            kind: "image",
            name: "selected-main.jpg",
            path: "aigc/selected-main.jpg",
            url: "/api/user/aigc-studio/assets/source-output-2/file",
            created_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    };

    const result = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [sourceWithPrimary, imageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      referenceAssetName: "selected-main.jpg",
      referencePreviewUrl: "/api/user/aigc-studio/assets/source-output-2/file",
    });
  });

  it("prefers generated outputs over stale source previews when connecting image nodes", () => {
    const generatedWithSourcePreview: AigcCanvasNode = {
      ...generatedSourceNode,
      data: {
        ...generatedSourceNode.data,
        assetName: "old-input.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/old-input/file",
      },
    };

    const result = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [generatedWithSourcePreview, imageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(result?.canvas.nodes[1]?.data).toMatchObject({
      referenceAssetName: "source-result.jpg",
      referencePreviewUrl: "/api/user/aigc-studio/assets/source-output/file",
    });
  });

  it("disconnects an image reference edge and clears the target reference business data", () => {
    const connected = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [generatedSourceNode, imageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    const disconnected = applyPortDisconnectionToCanvas({
      canvas: connected!.canvas,
      edgeId: "edge-image-source-image-1",
      t,
    });

    expect(disconnected?.canvas.edges).toEqual([]);
    expect(disconnected?.canvas.nodes[1]?.data).toMatchObject({
      referenceThumb: null,
      referenceAssetName: null,
      referencePreviewUrl: null,
      imageMode: "blank",
      inputUpdated: true,
    });
  });

  it("disconnects a mentioned reference and removes its prompt token while renumbering the rest", () => {
    const secondReferenceNode: AigcCanvasNode = {
      ...referenceNode,
      id: "asset-2",
      data: {
        ...referenceNode.data,
        assetName: "back.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/back/file",
      },
    };
    const thirdReferenceNode: AigcCanvasNode = {
      ...referenceNode,
      id: "asset-3",
      data: {
        ...referenceNode.data,
        assetName: "detail.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/detail/file",
      },
    };
    const mentionedImageNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        text: "参考 @图片1 @图片2 @图片3 做海报",
        composerText: "参考 @图片1 @图片2 @图片3 做海报",
        referencedAssets: [
          {
            id: "asset-1",
            alias: "图片1",
            name: "portrait.png",
            previewUrl: "/api/user/aigc-studio/assets/portrait.png/file",
            sourceNodeId: "asset-1",
          },
          {
            id: "asset-2",
            alias: "图片2",
            name: "back.png",
            previewUrl: "/api/user/aigc-studio/assets/back/file",
            sourceNodeId: "asset-2",
          },
          {
            id: "asset-3",
            alias: "图片3",
            name: "detail.png",
            previewUrl: "/api/user/aigc-studio/assets/detail/file",
            sourceNodeId: "asset-3",
          },
        ],
      },
    };
    const disconnected = applyPortDisconnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [
          referenceNode,
          secondReferenceNode,
          thirdReferenceNode,
          mentionedImageNode,
        ],
        edges: [
          {
            id: "edge-asset-1-image-1",
            source: "asset-1",
            target: "image-1",
            sourceHandle: "right",
            targetHandle: "left",
            data: { role: "reference_image" },
          },
          {
            id: "edge-asset-2-image-1",
            source: "asset-2",
            target: "image-1",
            sourceHandle: "right",
            targetHandle: "left",
            data: { role: "reference_image" },
          },
          {
            id: "edge-asset-3-image-1",
            source: "asset-3",
            target: "image-1",
            sourceHandle: "right",
            targetHandle: "left",
            data: { role: "reference_image" },
          },
        ],
      },
      edgeId: "edge-asset-1-image-1",
      t,
    });

    expect(disconnected?.canvas.edges.map((edge) => edge.source)).toEqual([
      "asset-2",
      "asset-3",
    ]);
    expect(disconnected?.canvas.nodes[3]?.data).toMatchObject({
      text: "参考 @图片1 @图片2 做海报",
      composerText: "参考 @图片1 @图片2 做海报",
      referencedAssets: [
        expect.objectContaining({
          alias: "图片1",
          sourceNodeId: "asset-2",
        }),
        expect.objectContaining({
          alias: "图片2",
          sourceNodeId: "asset-3",
        }),
      ],
      inputUpdated: true,
    });
  });

  it("cleans target reference data when an upstream source node is removed", () => {
    const connected = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [generatedSourceNode, imageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    const cleaned = cleanTargetDataForRemovedEdges({
      canvas: connected!.canvas,
      removedEdges: connected!.canvas.edges,
      t,
    });

    expect(cleaned.edges).toEqual([]);
    expect(cleaned.nodes[1]?.data).toMatchObject({
      referenceThumb: null,
      referenceAssetName: null,
      referencePreviewUrl: null,
      imageMode: "blank",
      inputUpdated: true,
    });
  });

  it("disconnects stale-role generated image edges as references without clearing the selected style", () => {
    const disconnected = applyPortDisconnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [
          generatedSourceNode,
          {
            ...imageNode,
            data: {
              ...imageNode.data,
              styleReferenceThumb: true,
              styleReferenceName: "一键国漫CGV2",
              styleReferencePreviewUrl:
                "/api/user/aigc-studio/styles/cgv2/cover",
              stylePreset: "一键国漫CGV2",
              styleKeywords: "国漫 CG 风格",
              referenceThumb: true,
              referenceAssetName: "source-result.jpg",
              referencePreviewUrl:
                "/api/user/aigc-studio/assets/source-output/file",
              imageMode: "image_to_image",
            },
          },
        ],
        edges: [
          {
            id: "edge-image-source-image-1",
            source: "image-source",
            target: "image-1",
            sourceHandle: "right",
            targetHandle: "left",
            data: { role: "style_template" },
          },
        ],
      },
      edgeId: "edge-image-source-image-1",
      t,
    });

    expect(disconnected?.canvas.edges).toEqual([]);
    expect(disconnected?.canvas.nodes[1]?.data).toMatchObject({
      styleReferenceThumb: true,
      styleReferenceName: "一键国漫CGV2",
      styleReferencePreviewUrl: "/api/user/aigc-studio/styles/cgv2/cover",
      stylePreset: "一键国漫CGV2",
      styleKeywords: "国漫 CG 风格",
      referenceThumb: null,
      referenceAssetName: null,
      referencePreviewUrl: null,
      imageMode: "blank",
      inputUpdated: true,
    });
  });

  it("disconnects styled generated image edges as references and clears the target thumbnail", () => {
    const styledGeneratedSourceNode: AigcCanvasNode = {
      ...generatedSourceNode,
      data: {
        ...generatedSourceNode.data,
        styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
        styleReferenceName: "一键国漫CGV2",
        styleReferencePreviewUrl: "/api/user/aigc-studio/styles/cgv2/cover",
      },
    };
    const connected = applyPortConnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [styledGeneratedSourceNode, imageNode],
      },
      anchorNodeId: "image-source",
      dropNodeId: "image-1",
      side: "right",
      t,
    });

    expect(connected?.canvas.edges[0]).toMatchObject({
      data: expect.objectContaining({ role: "reference_image" }),
    });

    const disconnected = applyPortDisconnectionToCanvas({
      canvas: connected!.canvas,
      edgeId: "edge-image-source-image-1",
      t,
    });

    expect(disconnected?.canvas.edges).toEqual([]);
    expect(disconnected?.canvas.nodes[1]?.data).toMatchObject({
      referenceThumb: null,
      referenceAssetName: null,
      referencePreviewUrl: null,
      imageMode: "blank",
      inputUpdated: true,
    });
  });

  it("disconnects a real style-template edge without clearing the image reference thumbnail", () => {
    const disconnected = applyPortDisconnectionToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [
          styleTemplateNode,
          {
            ...imageNode,
            data: {
              ...imageNode.data,
              styleReferenceThumb: true,
              styleReferenceName: "一键国漫CGV2",
              styleReferencePreviewUrl:
                "/api/user/aigc-studio/styles/cgv2/cover",
              styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
              effectTemplateUuids: ["dbc6dfc0990d46d28215bcdff87d53c3"],
              stylePreset: "一键国漫CGV2",
              styleKeywords: "国漫 CG 风格",
              referenceThumb: true,
              referenceAssetName: "source-result.jpg",
              referencePreviewUrl:
                "/api/user/aigc-studio/assets/source-output/file",
              imageMode: "image_to_image",
            },
          },
        ],
        edges: [
          {
            id: "edge-style-cgv2-image-1",
            source: "style-cgv2",
            target: "image-1",
            sourceHandle: "right",
            targetHandle: "left",
            data: { role: "style_template" },
          },
        ],
      },
      edgeId: "edge-style-cgv2-image-1",
      t,
    });

    expect(disconnected?.canvas.edges).toEqual([]);
    expect(disconnected?.canvas.nodes[1]?.data).toMatchObject({
      styleReferenceThumb: null,
      styleReferenceName: null,
      styleReferencePreviewUrl: null,
      styleTemplateUuid: null,
      effectTemplateUuids: null,
      stylePreset: null,
      styleKeywords: null,
      referenceThumb: true,
      referenceAssetName: "source-result.jpg",
      referencePreviewUrl: "/api/user/aigc-studio/assets/source-output/file",
      imageMode: "image_to_image",
      inputUpdated: true,
    });
  });

  it("repairs existing generated-image edges that were saved without a reference thumbnail", () => {
    const repaired = reconcileCanvasConnectionData({
      canvas: {
        ...canvasFixture(),
        nodes: [
          generatedSourceNode,
          {
            ...imageNode,
            data: {
              ...imageNode.data,
              referenceThumb: true,
              referenceAssetName: "上游生成图",
              referencePreviewUrl: "",
            },
          },
        ],
        edges: [
          {
            id: "edge-image-source-image-1",
            source: "image-source",
            target: "image-1",
            sourceHandle: "right",
            targetHandle: "left",
            data: { role: "reference_image" },
          },
        ],
      },
      t,
    });

    expect(repaired.changed).toBe(true);
    expect(repaired.canvas.nodes[1]?.data).toMatchObject({
      imageMode: "image_to_image",
      referenceThumb: true,
      referenceAssetName: "source-result.jpg",
      referencePreviewUrl: "/api/user/aigc-studio/assets/source-output/file",
      inputUpdated: true,
    });
  });
});
