import { describe, expect, it } from "vitest";

import type { AigcCanvas } from "../../api/modules/aigcStudio";
import { createImageAnnotationCanvas } from "./canvasAnnotationActions";
import { nodeVisualHeight, nodeVisualWidth } from "./canvasNodeUtils";

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [
    {
      id: "image-1",
      type: "image_generate",
      position: { x: 360, y: 80 },
      data: {
        title: "图片节点",
        imageState: "generated",
        outputs: [
          {
            id: "asset-1",
            kind: "image",
            name: "portrait.png",
            path: "/api/user/aigc-studio/assets/asset-1/file",
            width: 2848,
            height: 1600,
          },
        ],
      },
    },
  ],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-26T00:00:00Z",
  updated_at: "2026-06-26T00:00:00Z",
});

describe("canvasAnnotationActions", () => {
  it("creates a visible image annotation node connected from the source image", () => {
    const canvas = canvasFixture();
    const sourceNode = canvas.nodes[0]!;

    const result = createImageAnnotationCanvas({
      canvas,
      sourceNode,
      annotationPreviewUrl: "data:image/svg+xml,%3Csvg%20/%3E",
      sourcePreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
      instruction: "红圈区域需要变得更有皮肤质感",
      now: 123,
    });

    expect(result.annotationNode).toMatchObject({
      type: "reference_asset",
      data: {
        title: "标注",
        previewKind: "uploaded_source",
        assetRole: "image_annotation",
        assetKind: "image",
        assetName: "portrait-标注.svg",
        assetPreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
        annotationPreviewUrl: "data:image/svg+xml,%3Csvg%20/%3E",
        annotationSourcePreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
        sourceImageWidth: 2848,
        sourceImageHeight: 1600,
        annotationViewBoxWidth: 1000,
        annotationViewBoxHeight: 562,
        annotationInstruction: "红圈区域需要变得更有皮肤质感",
        referencePreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
        participatesInGeneration: true,
        isAnnotation: true,
      },
    });
    expect(result.canvas.nodes).toContain(result.annotationNode);
    expect(result.canvas.edges).toContainEqual(
      expect.objectContaining({
        source: "image-1",
        target: result.annotationNode.id,
        sourceHandle: "right",
        targetHandle: "left",
        data: { role: "image_annotation" },
      }),
    );
    expect(nodeVisualWidth(result.annotationNode)).toBe(560);
    expect(nodeVisualHeight(result.annotationNode)).toBe(315);
  });
});
