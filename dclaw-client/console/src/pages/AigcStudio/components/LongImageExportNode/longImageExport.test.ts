import { describe, expect, it } from "vitest";

import type { AigcCanvas } from "../../../../api/modules/aigcStudio";
import {
  calculateLongImageSlices,
  collectLongImageSections,
} from "./longImageExport";

describe("longImageExport", () => {
  const canvas: AigcCanvas = {
    id: "canvas-1",
    name: "小说推文长图",
    nodes: [
      {
        id: "text-1",
        type: "prompt",
        position: { x: 80, y: 80 },
        data: {
          title: "第一章",
          text: "她推开门，看见满城灯火。\n\n下一秒，命运开始反转。",
        },
      },
      {
        id: "image-1",
        type: "image_generate",
        position: { x: 520, y: 80 },
        data: {
          title: "剧情插图",
          imageState: "generated",
          outputs: [
            {
              id: "asset-1",
              kind: "image",
              name: "scene.png",
              path: "aigc_studio/scene.png",
              url: "/api/aigc-studio/assets/asset-1/file",
              mime_type: "image/png",
              created_at: "2026-07-02T00:00:00Z",
            },
          ],
        },
      },
      {
        id: "long-1",
        type: "long_image_export",
        position: { x: 960, y: 80 },
        data: {},
      },
    ],
    edges: [
      { id: "edge-text-long", source: "text-1", target: "long-1" },
      { id: "edge-image-long", source: "image-1", target: "long-1" },
    ],
    viewport: { x: 0, y: 0, zoom: 1 },
    created_at: "2026-07-02T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
  };

  it("collects upstream text paragraphs and generated image outputs in edge order", () => {
    const target = canvas.nodes[2]!;

    const sections = collectLongImageSections(canvas, target);

    expect(sections).toEqual([
      {
        id: "text-1-1",
        kind: "text",
        title: "第一章",
        text: "她推开门，看见满城灯火。",
        sourceNodeId: "text-1",
      },
      {
        id: "text-1-2",
        kind: "text",
        title: "第一章",
        text: "下一秒，命运开始反转。",
        sourceNodeId: "text-1",
      },
      {
        id: "image-1-asset-1",
        kind: "image",
        title: "剧情插图",
        imageUrl: "/api/aigc-studio/assets/asset-1/file",
        sourceNodeId: "image-1",
      },
    ]);
  });

  it("calculates upload slices that cover the full long-image height", () => {
    expect(
      calculateLongImageSlices({ height: 3120, sliceHeight: 1400 }),
    ).toEqual([
      { index: 1, y: 0, height: 1400 },
      { index: 2, y: 1400, height: 1400 },
      { index: 3, y: 2800, height: 320 },
    ]);
  });
});
