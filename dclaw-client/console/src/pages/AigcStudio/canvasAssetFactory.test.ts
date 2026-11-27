import { afterEach, describe, expect, it, vi } from "vitest";

import type { AigcAsset, AigcCanvas } from "../../api/modules/aigcStudio";
import {
  canvasPayload,
  canvasSignature,
  createAssetNodeFromUpload,
  localizeLegacyCanvas,
} from "./canvasAssetFactory";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Untitled AIGC canvas",
  nodes: [
    {
      id: "prompt-1",
      type: "prompt",
      position: { x: 80, y: 90 },
      data: {
        title: "Campaign prompt",
        text: "A cinematic product film concept with clear brand mood.",
      },
    },
  ],
  edges: [],
  viewport: { x: 10, y: 20, zoom: 0.8 },
  thumbnail: "thumb.png",
  meta: { version: 1 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasAssetFactory", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates save payloads and signatures from stable canvas fields", () => {
    const canvas = canvasFixture();

    expect(canvasPayload(canvas)).toEqual({
      name: "Untitled AIGC canvas",
      nodes: canvas.nodes,
      edges: canvas.edges,
      viewport: canvas.viewport,
      thumbnail: "thumb.png",
      meta: { version: 1 },
    });
    expect(canvasSignature(canvas)).toBe(
      JSON.stringify({
        id: "canvas-1",
        ...canvasPayload(canvas),
      }),
    );
  });

  it("omits transient node UI state from save payloads and signatures", () => {
    const canvas = {
      ...canvasFixture(),
      nodes: [
        {
          ...canvasFixture().nodes[0],
          data: {
            ...canvasFixture().nodes[0].data,
            activeTool: "style",
          },
        },
      ],
    };
    const sameCanvasWithDifferentUiState = {
      ...canvas,
      nodes: [
        {
          ...canvas.nodes[0],
          data: {
            ...canvas.nodes[0].data,
            activeTool: "mark",
          },
        },
      ],
    };

    expect(canvasPayload(canvas).nodes[0].data).not.toHaveProperty(
      "activeTool",
    );
    expect(canvasSignature(canvas)).toBe(
      canvasSignature(sameCanvasWithDifferentUiState),
    );
  });

  it("localizes legacy English canvas and default node text", () => {
    const localized = localizeLegacyCanvas(t, canvasFixture());

    expect(localized.name).toBe("未命名 AIGC 画布");
    expect(localized.nodes[0].data).toMatchObject({
      title: "营销提示词",
      text: "带有清晰品牌氛围的电影感产品片创意。",
    });
  });

  it("creates uploaded video reference asset nodes", () => {
    vi.spyOn(Date, "now").mockReturnValue(36);
    const asset: AigcAsset = {
      id: "asset-1",
      kind: "video",
      name: "clip.mp4",
      path: "aigc/uploads/clip.mp4",
      mime_type: "video/mp4",
      url: "https://assets.test/clip.mp4",
      created_at: "2026-06-12T00:00:00Z",
    };

    const node = createAssetNodeFromUpload(
      t,
      asset,
      new File(["video"], "local.mp4", { type: "video/mp4" }),
      2,
      { x: 100, y: 140 },
      5,
    );

    expect(node).toMatchObject({
      id: "asset-node-10-8",
      type: "reference_asset",
      position: { x: 188, y: 196 },
      data: {
        assetKind: "video",
        assetMimeType: "video/mp4",
        assetName: "clip.mp4",
        assetPath: "aigc/uploads/clip.mp4",
        assetPreviewUrl: "https://assets.test/clip.mp4",
        assetShape: "wide",
        previewKind: "uploaded_video",
        savedToAssets: true,
        title: "视频素材",
        uploadedAt: 36,
      },
    });
  });
});
