import { describe, expect, it } from "vitest";

import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";
import {
  appendPortNode,
  appendTemplateParts,
  createPortEdge,
  portNodePosition,
  repositionTemplateNodes,
} from "./canvasTemplateActions";

const sourceNode: AigcCanvasNode = {
  id: "source-1",
  type: "prompt",
  position: { x: 100, y: 140 },
  data: { title: "Prompt" },
};

const targetNode: AigcCanvasNode = {
  id: "target-1",
  type: "image_generate",
  position: { x: 420, y: 160 },
  data: { title: "Image" },
};

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [sourceNode],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasTemplateActions", () => {
  it("repositions template nodes around an anchor and appends parts", () => {
    const templateNodes = [
      { ...sourceNode, position: { x: 130, y: 170 } },
      { ...targetNode, position: { x: 500, y: 190 } },
    ];
    const templateEdge: AigcCanvasEdge = {
      id: "edge-source-target",
      source: "source-1",
      target: "target-1",
      sourceHandle: "right",
      targetHandle: "left",
    };

    const nodes = repositionTemplateNodes(templateNodes, { x: 300, y: 400 });
    const canvas = appendTemplateParts({
      canvas: canvasFixture(),
      nodes,
      edges: [templateEdge],
    });

    expect(nodes.map((node) => node.position)).toEqual([
      { x: 300, y: 400 },
      { x: 670, y: 420 },
    ]);
    expect(canvas.nodes.map((node) => node.id)).toEqual([
      "source-1",
      "source-1",
      "target-1",
    ]);
    expect(canvas.edges).toEqual([templateEdge]);
  });

  it("calculates port-node positions and edge direction for both sides", () => {
    const leftPosition = portNodePosition({
      anchorNode: targetNode,
      side: "left",
      anchorWidth: 560,
      createdWidth: 400,
    });
    const rightPosition = portNodePosition({
      anchorNode: sourceNode,
      side: "right",
      anchorWidth: 400,
      createdWidth: 560,
    });

    expect(leftPosition).toEqual({ x: 0, y: 160 });
    expect(rightPosition).toEqual({ x: 670, y: 140 });
    expect(
      createPortEdge({
        anchorNode: sourceNode,
        createdNode: targetNode,
        side: "right",
        role: "prompt",
      }),
    ).toEqual({
      id: "edge-source-1-target-1",
      source: "source-1",
      target: "target-1",
      sourceHandle: "right",
      targetHandle: "left",
      data: { role: "prompt" },
    });
  });

  it("appends a port node and its connecting edge to the canvas", () => {
    const edge = createPortEdge({
      anchorNode: sourceNode,
      createdNode: targetNode,
      side: "right",
      role: "reference_image",
    });
    const canvas = appendPortNode({
      canvas: canvasFixture(),
      node: targetNode,
      edge,
    });

    expect(canvas.nodes.map((node) => node.id)).toEqual([
      "source-1",
      "target-1",
    ]);
    expect(canvas.edges).toEqual([edge]);
  });
});
