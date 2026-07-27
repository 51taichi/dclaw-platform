import { afterEach, describe, expect, it, vi } from "vitest";

import type { AigcAsset, AigcCanvas } from "../../api/modules/aigcStudio";
import type { CanvasAssetRecord } from "./canvasNodeUtils";
import {
  appendCanvasNodes,
  buildUploadedAssetNodes,
  createAssetNodeFromRecord,
  defaultAssetNodePosition,
  filterCanvasAssetFiles,
  replaceSourceImageReferences,
} from "./canvasAssetActions";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [
    {
      id: "source-1",
      type: "reference_asset",
      position: { x: 80, y: 90 },
      data: { assetName: "old.png", assetPreviewUrl: "old-url" },
    },
    {
      id: "image-1",
      type: "image_generate",
      position: { x: 360, y: 90 },
      data: {},
    },
  ],
  edges: [
    {
      id: "edge-source-image",
      source: "source-1",
      target: "image-1",
      sourceHandle: "right",
      targetHandle: "left",
    },
  ],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasAssetActions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("filters upload files and builds uploaded asset nodes", () => {
    vi.spyOn(Date, "now").mockReturnValue(36);
    const imageFile = new File(["image"], "image.png", { type: "image/png" });
    const textFile = new File(["text"], "note.txt", { type: "text/plain" });
    const asset: AigcAsset = {
      id: "asset-1",
      kind: "image",
      name: "image.png",
      path: "uploads/image.png",
      url: "https://assets.test/image.png",
      mime_type: "image/png",
      created_at: "2026-06-12T00:00:00Z",
    };

    const files = filterCanvasAssetFiles([imageFile, textFile]);
    const nodes = buildUploadedAssetNodes({
      t,
      files,
      assets: [asset],
      position: { x: 100, y: 120 },
      nodeCount: 2,
    });

    expect(files).toEqual([imageFile]);
    expect(nodes).toHaveLength(1);
    expect(nodes[0]).toMatchObject({
      id: "asset-node-10-3",
      position: { x: 100, y: 120 },
      data: {
        title: "图片节点",
        assetName: "image.png",
        assetPreviewUrl: "https://assets.test/image.png",
      },
    });
  });

  it("creates nodes from saved asset records and appends nodes to a canvas", () => {
    vi.spyOn(Date, "now").mockReturnValue(36);
    const record: CanvasAssetRecord = {
      id: "record-1",
      title: "Brand shot",
      kind: "素材",
      nodeType: "reference_asset",
      sourceNodeId: "source-1",
      text: "lighting notes",
      previewKind: "uploaded_source",
      assetPreviewUrl: "https://assets.test/brand.png",
      createdAt: 36,
    };

    const node = createAssetNodeFromRecord({
      record,
      nodeCount: 2,
    });
    const canvas = appendCanvasNodes(canvasFixture(), [node]);

    expect(defaultAssetNodePosition(5)).toEqual({ x: 380, y: 310 });
    expect(node).toMatchObject({
      id: "asset-node-10-3",
      type: "reference_asset",
      position: { x: 640, y: 130 },
      data: {
        title: "Brand shot",
        text: "lighting notes",
        previewKind: "uploaded_source",
        assetPreviewUrl: "https://assets.test/brand.png",
        assetName: "Brand shot",
      },
    });
    expect(canvas.nodes[canvas.nodes.length - 1]?.id).toBe("asset-node-10-3");
  });

  it("replaces source image previews and updates downstream references", () => {
    const updated = replaceSourceImageReferences({
      canvas: canvasFixture(),
      sourceNodeId: "source-1",
      assetName: "new.png",
      assetPreviewUrl: "new-url",
    });

    expect(updated.nodes[0]?.data).toMatchObject({
      assetName: "new.png",
      assetPreviewUrl: "new-url",
    });
    expect(updated.nodes[1]?.data).toMatchObject({
      referenceAssetName: "new.png",
      referencePreviewUrl: "new-url",
      inputUpdated: true,
    });
  });
});
