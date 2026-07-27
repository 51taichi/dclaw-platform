import { describe, expect, it } from "vitest";

import type { AigcCanvas, AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  cloneCanvasNode,
  deleteCanvasNode,
  duplicateCanvasNodeWithEdges,
  pasteCanvasNode,
  restoreDeletedCanvasNode,
} from "./canvasCommands";

const promptNode: AigcCanvasNode = {
  id: "prompt-1",
  type: "prompt",
  position: { x: 80, y: 90 },
  data: { title: "Prompt" },
};

const imageNode: AigcCanvasNode = {
  id: "image-1",
  type: "image_generate",
  position: { x: 360, y: 90 },
  data: { title: "Image" },
};

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [promptNode, imageNode],
  edges: [
    {
      id: "edge-prompt-image",
      source: "prompt-1",
      target: "image-1",
      sourceHandle: "right",
      targetHandle: "left",
    },
  ],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasCommands", () => {
  it("clones and pastes nodes with stable offsets and copied titles", () => {
    expect(
      cloneCanvasNode({
        node: promptNode,
        suffix: "copy-1",
        fallbackTitle: "提示词/文本",
      }),
    ).toMatchObject({
      id: "prompt-copy-1",
      position: { x: 124, y: 134 },
      data: { title: "Prompt 副本" },
    });

    const { canvas, node } = pasteCanvasNode({
      canvas: canvasFixture(),
      node: promptNode,
      suffix: "paste-1",
    });

    expect(node.id).toBe("prompt-paste-1");
    expect(node.position).toEqual({ x: 152, y: 162 });
    expect(canvas.nodes.map((item) => item.id)).toEqual([
      "prompt-1",
      "image-1",
      "prompt-paste-1",
    ]);
  });

  it("duplicates a node and rewires copied adjacent edges", () => {
    const { canvas, node } = duplicateCanvasNodeWithEdges({
      canvas: canvasFixture(),
      node: promptNode,
      suffix: "copy-1",
    });

    expect(node.id).toBe("prompt-copy-1");
    expect(canvas.edges).toEqual([
      canvasFixture().edges[0],
      {
        id: "edge-edge-prompt-image-prompt-copy-1",
        source: "prompt-copy-1",
        target: "image-1",
        sourceHandle: "right",
        targetHandle: "left",
      },
    ]);
  });

  it("deletes and restores nodes with their connected edges", () => {
    const deleted = deleteCanvasNode({
      canvas: canvasFixture(),
      nodeId: "image-1",
      selectedNodeId: "image-1",
    });

    expect(deleted?.canvas.nodes.map((node) => node.id)).toEqual(["prompt-1"]);
    expect(deleted?.canvas.edges).toEqual([]);
    expect(deleted?.nextSelectedNodeId).toBeNull();
    expect(deleted?.snapshot.node.id).toBe("image-1");
    expect(deleted?.snapshot.edges).toHaveLength(1);

    const restored = restoreDeletedCanvasNode({
      canvas: deleted!.canvas,
      snapshot: deleted!.snapshot,
    });

    expect(restored?.canvas.nodes.map((node) => node.id)).toEqual([
      "prompt-1",
      "image-1",
    ]);
    expect(restored?.canvas.edges).toHaveLength(1);
    expect(restored?.selectedNodeId).toBe("image-1");
  });
});
