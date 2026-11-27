import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvas,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import { useTextNodeWorkflow } from "./useTextNodeWorkflow";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const canvasWithNode = (node: AigcCanvasNode): AigcCanvas => ({
  id: "canvas-1",
  name: "测试画布",
  nodes: [node],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-11T00:00:00Z",
  updated_at: "2026-06-11T00:00:00Z",
});

const textNode: AigcCanvasNode = {
  id: "text-1",
  type: "prompt",
  position: { x: 100, y: 120 },
  data: {
    title: "文本节点",
    showTryOptions: true,
  },
};

describe("useTextNodeWorkflow", () => {
  it("creates a downstream video node when text-to-video is selected", () => {
    const commitCanvas = vi.fn();
    const updateNodeData = vi.fn();
    const setSelectedNodeId = vi.fn();
    const setEditingTextNodeId = vi.fn();
    const setTextModelMenuNodeId = vi.fn();
    const setContextMenu = vi.fn();
    const runCreatedNode = vi.fn();

    const { result } = renderHook(() =>
      useTextNodeWorkflow({
        activeCanvas: canvasWithNode(textNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        setEditingTextNodeId,
        setTextModelMenuNodeId,
        setContextMenu,
        runCreatedNode,
        t,
      }),
    );

    act(() => {
      result.current.handleTextTry(textNode, "text_to_video");
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    expect(updatedCanvas.nodes).toHaveLength(2);
    expect(updatedCanvas.nodes[0].data).toMatchObject({
      textMode: "text_to_video",
      showTryOptions: false,
    });
    expect(updatedCanvas.nodes[1]).toMatchObject({
      type: "video_generate",
      position: { x: 530, y: 112 },
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "text-1",
        target: updatedCanvas.nodes[1].id,
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith(updatedCanvas.nodes[1].id);
    expect(setTextModelMenuNodeId).toHaveBeenCalledWith(null);
    expect(setContextMenu).toHaveBeenCalledWith(null);
    expect(runCreatedNode).toHaveBeenCalledWith(
      updatedCanvas.nodes[1],
      updatedCanvas,
    );
  });

  it("asks the canvas layer to run composer text as a text job", () => {
    const commitCanvas = vi.fn();
    const updateNodeData = vi.fn();
    const setEditingTextNodeId = vi.fn();
    const runTextNode = vi.fn();

    const { result } = renderHook(() =>
      useTextNodeWorkflow({
        activeCanvas: canvasWithNode(textNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId: vi.fn(),
        setEditingTextNodeId,
        setTextModelMenuNodeId: vi.fn(),
        setContextMenu: vi.fn(),
        runTextNode,
        t,
      }),
    );

    act(() => {
      result.current.handleTextComposerSubmit({
        ...textNode,
        data: {
          ...textNode.data,
          composerText: "给我写一个爱情故事",
          modelLabel: "GVLM 3.1",
          providerId: "modelscope",
          providerName: "ModelScope",
          modelId: "gvlm-3.1",
        },
      });
    });

    expect(setEditingTextNodeId).toHaveBeenCalledWith(null);
    expect(updateNodeData).not.toHaveBeenCalled();
    expect(commitCanvas).not.toHaveBeenCalled();
    expect(runTextNode).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "text-1",
        data: expect.objectContaining({
          textMode: "generated",
          text: "给我写一个爱情故事",
          lastRunPrompt: "给我写一个爱情故事",
          modelLabel: "GVLM 3.1",
        }),
      }),
      expect.objectContaining({
        nodes: [
          expect.objectContaining({
            id: "text-1",
            data: expect.objectContaining({
              text: "给我写一个爱情故事",
              showTryOptions: false,
            }),
          }),
        ],
      }),
    );
  });
});
