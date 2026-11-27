import { act, renderHook } from "@testing-library/react";
import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import type { ScriptShot } from "../ScriptNode/scriptNodeState";
import { useStoryboardWorkflow } from "./useStoryboardWorkflow";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const shots: ScriptShot[] = [
  {
    id: "shot-1",
    no: 1,
    duration: 4,
    imageDescription: "深夜办公室蓝光",
    character: "沈昭昭现代",
    characterDescription: "白衬衫，疲惫",
    scene: "现代办公室",
    shotType: "特写",
    action: "手指停下",
    emotion: "疲惫",
    dialogue: "无",
    prompt: "电影感办公室特写，蓝色屏幕光",
    videoPrompt: "镜头缓慢推进",
  },
  {
    id: "shot-2",
    no: 2,
    duration: 5,
    imageDescription: "盛唐金殿惊醒",
    character: "沈昭昭唐代",
    characterDescription: "唐代官服",
    scene: "盛唐金銮殿",
    shotType: "全景",
    action: "猛然抬头",
    emotion: "震惊",
    dialogue: "这是唐朝？",
    prompt: "盛唐金銮殿全景，女主惊醒",
    videoPrompt: "镜头俯冲下降",
  },
];

const scriptNode = (
  data: AigcCanvasNode["data"] = {},
): AigcCanvasNode => ({
  id: "script-1",
  type: "script_generate",
  position: { x: 360, y: 120 },
  data: {
    title: "脚本生成器",
    scriptMode: "script_ready",
    scriptShots: shots,
    selectedShotIds: shots.map((shot) => shot.id),
    storyboardStyle: "Lib Image",
    ...data,
  },
});

const canvas = (nodes: AigcCanvasNode[] = [scriptNode()]): AigcCanvas => ({
  id: "canvas-1",
  name: "画布 1",
  nodes,
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-20T00:00:00.000Z",
  updated_at: "2026-06-20T00:00:00.000Z",
});

type SetActiveCanvas = Dispatch<SetStateAction<AigcCanvas | null>>;
type SetCanvases = Dispatch<SetStateAction<AigcCanvas[]>>;
type SetSelectedNodeId = Dispatch<SetStateAction<string | null>>;
type ConnectCanvasNodes = (source: string, target: string) => AigcCanvasEdge;

function renderStoryboardWorkflow(activeCanvas: AigcCanvas) {
  const commitCanvas = vi.fn<(canvas: AigcCanvas) => void>();
  const updateNodeData = vi.fn<(nodeId: string, data: Record<string, unknown>) => void>();
  const setActiveCanvas = vi.fn<SetActiveCanvas>();
  const setCanvases = vi.fn<SetCanvases>();
  const setSelectedNodeId = vi.fn<SetSelectedNodeId>();
  const connectCanvasNodes = vi.fn<ConnectCanvasNodes>((source, target) => ({
    id: `edge-${source}-${target}`,
    source,
    target,
    sourceHandle: "right",
    targetHandle: "left",
  }));

  return {
    commitCanvas,
    updateNodeData,
    setSelectedNodeId,
    connectCanvasNodes,
    ...renderHook(() =>
      useStoryboardWorkflow({
        activeCanvas,
        commitCanvas,
        updateNodeData,
        setActiveCanvas,
        setCanvases,
        setSelectedNodeId,
        setTextModelMenuNodeId: vi.fn(),
        setImageComposerMenu: vi.fn(),
        setVideoComposerMenu: vi.fn(),
        setPortMenu: vi.fn(),
        nodeVisualWidth: () => 350,
        connectCanvasNodes,
        modelOptions: [],
        t,
      }),
    ),
  };
}

describe("useStoryboardWorkflow", () => {
  it("creates real image nodes for selected script shots", () => {
    const node = scriptNode({ selectedShotIds: ["shot-1", "shot-2"] });
    const activeCanvas = canvas([node]);
    const { result, commitCanvas, setSelectedNodeId } =
      renderStoryboardWorkflow(activeCanvas);

    act(() => {
      result.current.handleStoryboardComposerSubmit(node);
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updated = commitCanvas.mock.calls[0]![0];
    const imageNodes = updated.nodes.filter(
      (item) => item.type === "image_generate",
    );

    expect(imageNodes).toHaveLength(2);
    expect(imageNodes).toEqual([
      expect.objectContaining({
        id: "storyboard-image-script-1-shot-1",
        data: expect.objectContaining({
          imageMode: "text_to_image",
          text: "电影感办公室特写，蓝色屏幕光",
          composerText: "电影感办公室特写，蓝色屏幕光",
          sourceScriptNodeId: "script-1",
          sourceShotId: "shot-1",
          storyboardShotNo: 1,
          storyboardStyle: "Lib Image",
          aspectRatio: "自适应",
          resolution: "2K",
          imageCount: 1,
        }),
      }),
      expect.objectContaining({
        id: "storyboard-image-script-1-shot-2",
        data: expect.objectContaining({
          imageMode: "text_to_image",
          text: "盛唐金銮殿全景，女主惊醒",
          sourceShotId: "shot-2",
          storyboardShotNo: 2,
        }),
      }),
    ]);
    expect(updated.edges).toEqual([
      expect.objectContaining({
        source: "script-1",
        target: "storyboard-image-script-1-shot-1",
      }),
      expect.objectContaining({
        source: "script-1",
        target: "storyboard-image-script-1-shot-2",
      }),
    ]);
    expect(updated.nodes.find((item) => item.id === "script-1")?.data).toEqual(
      expect.objectContaining({
        storyboardImageNodeIds: [
          "storyboard-image-script-1-shot-1",
          "storyboard-image-script-1-shot-2",
        ],
        storyboardImageShotIds: ["shot-1", "shot-2"],
        storyboardBatchDialogOpen: false,
      }),
    );
    expect(setSelectedNodeId).toHaveBeenCalledWith(
      "storyboard-image-script-1-shot-1",
    );
  });
});
