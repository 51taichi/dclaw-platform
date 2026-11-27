import { act, renderHook } from "@testing-library/react";
import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import { useScriptNodeWorkflow } from "./useScriptNodeWorkflow";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const scriptNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "script-1",
  type: "script_generate",
  position: { x: 360, y: 120 },
  data,
});

const canvas = (
  nodes: AigcCanvasNode[] = [scriptNode()],
  edges: AigcCanvas["edges"] = [],
): AigcCanvas => ({
  id: "canvas-1",
  name: "画布 1",
  nodes,
  edges,
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-20T00:00:00.000Z",
  updated_at: "2026-06-20T00:00:00.000Z",
});

type UpdateNodeData = (nodeId: string, data: Record<string, unknown>) => void;
type SetActiveCanvas = Dispatch<SetStateAction<AigcCanvas | null>>;
type SetCanvases = Dispatch<SetStateAction<AigcCanvas[]>>;
type SetSelectedNodeId = Dispatch<SetStateAction<string | null>>;
type ConnectCanvasNodes = (source: string, target: string) => AigcCanvasEdge;
type RunScriptNode = (
  node: AigcCanvasNode,
  canvas: AigcCanvas,
) => void | Promise<void>;

const createUpdateNodeDataMock = () => vi.fn<UpdateNodeData>();
const createSetActiveCanvasMock = () => vi.fn<SetActiveCanvas>();
const createSetCanvasesMock = () => vi.fn<SetCanvases>();
const createSetSelectedNodeIdMock = () => vi.fn<SetSelectedNodeId>();
const createConnectCanvasNodesMock = () =>
  vi.fn<ConnectCanvasNodes>((source, target) => ({
    id: `${source}-${target}`,
    source,
    target,
  }));
const createRunScriptNodeMock = () => vi.fn<RunScriptNode>();
const createRunAssetImageNodeMock = () => vi.fn<RunScriptNode>();

function renderScriptWorkflow({
  activeCanvas = null,
  updateNodeData = createUpdateNodeDataMock(),
  setActiveCanvas = createSetActiveCanvasMock(),
  setCanvases = createSetCanvasesMock(),
  setSelectedNodeId = createSetSelectedNodeIdMock(),
  connectCanvasNodes = createConnectCanvasNodesMock(),
  runScriptNode = createRunScriptNodeMock(),
  runAssetImageNode = createRunAssetImageNodeMock(),
}: {
  activeCanvas?: AigcCanvas | null;
  updateNodeData?: ReturnType<typeof createUpdateNodeDataMock>;
  setActiveCanvas?: ReturnType<typeof createSetActiveCanvasMock>;
  setCanvases?: ReturnType<typeof createSetCanvasesMock>;
  setSelectedNodeId?: ReturnType<typeof createSetSelectedNodeIdMock>;
  connectCanvasNodes?: ReturnType<typeof createConnectCanvasNodesMock>;
  runScriptNode?: ReturnType<typeof createRunScriptNodeMock>;
  runAssetImageNode?: ReturnType<typeof createRunAssetImageNodeMock>;
} = {}) {
  return {
    updateNodeData,
    setActiveCanvas,
    setCanvases,
    setSelectedNodeId,
    connectCanvasNodes,
    runScriptNode,
    runAssetImageNode,
    ...renderHook(() =>
      useScriptNodeWorkflow({
        activeCanvas,
        updateNodeData,
        setActiveCanvas,
        setCanvases,
        setSelectedNodeId,
        setAddMenuOpen: vi.fn(),
        setContextMenu: vi.fn(),
        setCanvasContextMenu: vi.fn(),
        setQuickTemplateMenu: vi.fn(),
        setPortMenu: vi.fn(),
        setTextModelMenuNodeId: vi.fn(),
        setImageComposerMenu: vi.fn(),
        setVideoComposerMenu: vi.fn(),
        connectCanvasNodes,
        runScriptNode,
        runAssetImageNode,
        storyboardWorkflow: {
          handleStoryboardComposerSubmit: vi.fn(),
        },
        t,
      }),
    ),
  };
}

describe("useScriptNodeWorkflow", () => {
  it("does not create a linked text node when choosing the default script workflow", () => {
    const node = scriptNode();
    const activeCanvas = canvas([node]);
    const {
      result,
      updateNodeData,
      setActiveCanvas,
      setCanvases,
      setSelectedNodeId,
    } = renderScriptWorkflow({
      activeCanvas,
    });

    act(() => {
      result.current.handleScriptTry(node, "script");
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      scriptInputKind: "script",
      scriptPrompt: "描述剧情或添加角色参考、视频参考等，为你生成分镜脚本",
      composerPlaceholder: "描述剧情片段、故事，为你生成分镜脚本",
      composerText: "",
      scriptMode: "idle",
      scriptView: "script",
      scriptWorkflowStep: "shots",
      scriptSourceNodeId: null,
    });
    expect(setActiveCanvas).not.toHaveBeenCalled();
    expect(setCanvases).not.toHaveBeenCalled();
    expect(setSelectedNodeId).toHaveBeenCalledWith("script-1");
  });

  it("submits script generation through the real run path without filling demo shots", () => {
    const node = scriptNode({
      scriptPrompt: "根据脚本生成分镜",
      composerText: "现代办公室加班后穿越盛唐",
      scriptInputKind: "write",
    });
    const activeCanvas = canvas([node]);
    const { result, runScriptNode, updateNodeData } = renderScriptWorkflow({
      activeCanvas,
    });

    act(() => {
      result.current.handleScriptComposerSubmit(node);
    });

    expect(updateNodeData).not.toHaveBeenCalled();
    expect(runScriptNode).toHaveBeenCalledTimes(1);
    const [nodeSnapshot, updatedCanvas] = runScriptNode.mock.calls[0]!;
    expect(nodeSnapshot.data).toEqual(
      expect.objectContaining({
        scriptMode: "generating_script",
        scriptProgress: 4,
        scriptView: "script",
        scriptWorkflowStep: "shots",
        scriptParseStatus: null,
        job_error: null,
        outputs: [],
        scriptShots: [],
        selectedShotIds: [],
      }),
    );
    expect(updatedCanvas.nodes.find((item) => item.id === "script-1")).toEqual(
      nodeSnapshot,
    );
  });

  it("reruns a script node through the real run path without timer completion", () => {
    vi.useFakeTimers();
    const node = scriptNode({
      scriptMode: "script_ready",
      scriptShots: [
        {
          id: "shot-custom",
          no: 1,
          duration: 3,
          imageDescription: "旧镜头",
          character: "",
          characterDescription: "",
          scene: "",
          shotType: "",
          action: "",
          emotion: "",
          dialogue: "",
          prompt: "旧提示词",
          videoPrompt: "旧视频提示词",
        },
      ],
    });
    const activeCanvas = canvas([node]);
    const { result, runScriptNode, updateNodeData } = renderScriptWorkflow({
      activeCanvas,
    });

    act(() => {
      result.current.handleScriptRegenerate(node);
      vi.runOnlyPendingTimers();
    });

    expect(runScriptNode).toHaveBeenCalledTimes(1);
    expect(updateNodeData).not.toHaveBeenCalledWith(
      "script-1",
      expect.objectContaining({ scriptMode: "script_ready" }),
    );
    vi.useRealTimers();
  });

  it("selects a script asset for the preparation detail panel", () => {
    const { result, updateNodeData } = renderScriptWorkflow();

    act(() => {
      result.current.handleScriptAssetSelect(
        scriptNode(),
        "character:沈昭昭现代",
      );
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      selectedScriptAssetId: "character:沈昭昭现代",
    });
  });

  it("starts one script asset generation before marking it ready", () => {
    vi.useFakeTimers();
    const { result, updateNodeData } = renderScriptWorkflow();
    const node = scriptNode({
      scriptAssetStates: {
        "scene:现代办公室，凌乱桌面，电脑屏幕发光": "uploaded",
      },
    });

    act(() => {
      result.current.handleScriptAssetGenerate(node, "character:沈昭昭现代");
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      selectedScriptAssetId: "character:沈昭昭现代",
      scriptAssetStates: {
        "character:沈昭昭现代": "generating",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光": "uploaded",
      },
      scriptAssetProgress: 4,
    });

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(updateNodeData).toHaveBeenLastCalledWith("script-1", {
      selectedScriptAssetId: "character:沈昭昭现代",
      scriptAssetStates: {
        "character:沈昭昭现代": "ready",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光": "uploaded",
      },
      scriptAssetProgress: 100,
    });
    vi.useRealTimers();
  });

  it("starts every requested script asset generation before marking them ready", () => {
    vi.useFakeTimers();
    const { result, updateNodeData } = renderScriptWorkflow();

    act(() => {
      result.current.handleScriptAssetsGenerateAll(scriptNode(), [
        "character:沈昭昭现代",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光",
        "prop:屏幕",
      ]);
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      scriptAssetStates: {
        "character:沈昭昭现代": "generating",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光": "generating",
        "prop:屏幕": "generating",
      },
      scriptAssetProgress: 4,
    });

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(updateNodeData).toHaveBeenLastCalledWith("script-1", {
      scriptAssetStates: {
        "character:沈昭昭现代": "ready",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光": "ready",
        "prop:屏幕": "ready",
      },
      scriptAssetProgress: 100,
    });
    vi.useRealTimers();
  });

  it("creates real image nodes after generating all script assets", () => {
    const initialNode = scriptNode({ title: "诡异爱情故事" });
    const activeCanvas = canvas([initialNode]);
    const {
      result,
      updateNodeData,
      setActiveCanvas,
      setCanvases,
      runAssetImageNode,
    } = renderScriptWorkflow({ activeCanvas });

    act(() => {
      result.current.handleScriptAssetsGenerateAll(initialNode, [
        "character:林风",
        "scene:废弃便利店",
        "prop:医疗口罩",
      ]);
    });

    const updatedCanvas = setActiveCanvas.mock.calls[
      setActiveCanvas.mock.calls.length - 1
    ]?.[0] as AigcCanvas;
    const updatedScriptNode = updatedCanvas.nodes.find(
      (node) => node.id === "script-1",
    );
    const assetNodes = updatedCanvas.nodes.filter(
      (node) => node.type === "image_generate",
    );

    expect(assetNodes).toHaveLength(3);
    expect(assetNodes).toEqual([
      expect.objectContaining({
        id: "script-asset-script-1-character-林风",
        data: expect.objectContaining({
          imageMode: "text_to_image",
          imageState: "generating",
          job_status: "queued",
          sourceScriptNodeId: "script-1",
          scriptAssetId: "character:林风",
          scriptAssetKind: "character",
          scriptAssetLabel: "林风",
          text: expect.stringContaining("角色资产图"),
        }),
      }),
      expect.objectContaining({
        id: "script-asset-script-1-scene-废弃便利店",
        data: expect.objectContaining({
          scriptAssetId: "scene:废弃便利店",
          scriptAssetKind: "scene",
          scriptAssetLabel: "废弃便利店",
          text: expect.stringContaining("场景资产图"),
        }),
      }),
      expect.objectContaining({
        id: "script-asset-script-1-prop-医疗口罩",
        data: expect.objectContaining({
          scriptAssetId: "prop:医疗口罩",
          scriptAssetKind: "prop",
          scriptAssetLabel: "医疗口罩",
          text: expect.stringContaining("道具资产图"),
        }),
      }),
    ]);
    expect(updatedScriptNode?.data).toEqual(
      expect.objectContaining({
        scriptAssetNodeIds: [
          "script-asset-script-1-character-林风",
          "script-asset-script-1-scene-废弃便利店",
          "script-asset-script-1-prop-医疗口罩",
        ],
        scriptAssetProgress: null,
        scriptAssetStates: {
          "character:林风": "generating",
          "scene:废弃便利店": "generating",
          "prop:医疗口罩": "generating",
        },
      }),
    );
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "script-1",
        target: "script-asset-script-1-character-林风",
      }),
      expect.objectContaining({
        source: "script-1",
        target: "script-asset-script-1-scene-废弃便利店",
      }),
      expect.objectContaining({
        source: "script-1",
        target: "script-asset-script-1-prop-医疗口罩",
      }),
    ]);
    expect(setCanvases).toHaveBeenCalled();
    expect(runAssetImageNode).toHaveBeenCalledTimes(3);
    expect(runAssetImageNode.mock.calls.map((call) => call[0].id)).toEqual([
      "script-asset-script-1-character-林风",
      "script-asset-script-1-scene-废弃便利店",
      "script-asset-script-1-prop-医疗口罩",
    ]);
    expect(
      runAssetImageNode.mock.calls.every((call) => call[1] === updatedCanvas),
    ).toBe(true);
    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      scriptAssetStates: {
        "character:林风": "generating",
        "scene:废弃便利店": "generating",
        "prop:医疗口罩": "generating",
      },
      scriptAssetProgress: 4,
    });
  });

  it("applies selected image generation settings to script asset nodes", () => {
    const initialNode = scriptNode({ title: "诡异爱情故事" });
    const activeCanvas = canvas([initialNode]);
    const { result, setActiveCanvas } = renderScriptWorkflow({ activeCanvas });

    act(() => {
      result.current.handleScriptAssetsGenerateAll(
        initialNode,
        ["scene:废弃便利店"],
        {
          modelLabel: "Seedream 4.6",
          providerId: "seedream",
          providerName: "Seedream",
          modelId: "seedream-4-6",
          modelCapability: "text_to_image",
          imageQuality: "高画质",
          resolution: "4K",
          aspectRatio: "21:9",
        },
      );
    });

    const updatedCanvas = setActiveCanvas.mock.calls[
      setActiveCanvas.mock.calls.length - 1
    ]?.[0] as AigcCanvas;

    expect(
      updatedCanvas.nodes.find(
        (node) => node.id === "script-asset-script-1-scene-废弃便利店",
      )?.data,
    ).toEqual(
      expect.objectContaining({
        modelLabel: "Seedream 4.6",
        providerId: "seedream",
        providerName: "Seedream",
        modelId: "seedream-4-6",
        modelCapability: "text_to_image",
        imageQuality: "高画质",
        resolution: "4K",
        aspectRatio: "21:9",
      }),
    );
  });

  it("updates existing script asset image nodes instead of creating duplicates", () => {
    const initialNode = scriptNode({
      scriptAssetNodeIds: ["script-asset-script-1-character-林风"],
      scriptAssetStates: {
        "character:林风": "generated",
      },
    });
    const existingAssetNode = {
      id: "script-asset-script-1-character-林风",
      type: "image_generate",
      position: { x: 80, y: 120 },
      data: {
        imageMode: "text_to_image",
        sourceScriptNodeId: "script-1",
        scriptAssetId: "character:林风",
        scriptAssetKind: "character",
        scriptAssetLabel: "林风",
      },
    };
    const activeCanvas = canvas(
      [initialNode, existingAssetNode],
      [
        {
          id: "edge-script-character",
          source: "script-1",
          target: "script-asset-script-1-character-林风",
        },
      ],
    );
    const { result, setActiveCanvas } = renderScriptWorkflow({ activeCanvas });

    act(() => {
      result.current.handleScriptAssetsGenerateAll(initialNode, [
        "character:林风",
        "scene:血月街道",
      ]);
    });

    const updatedCanvas = setActiveCanvas.mock.calls[
      setActiveCanvas.mock.calls.length - 1
    ]?.[0] as AigcCanvas;

    expect(
      updatedCanvas.nodes.filter(
        (node) => node.id === "script-asset-script-1-character-林风",
      ),
    ).toHaveLength(1);
    expect(
      updatedCanvas.edges.filter(
        (edge) =>
          edge.source === "script-1" &&
          edge.target === "script-asset-script-1-character-林风",
      ),
    ).toHaveLength(1);
    expect(
      updatedCanvas.nodes.find(
        (node) => node.id === "script-asset-script-1-scene-血月街道",
      ),
    ).toMatchObject({
      type: "image_generate",
      data: expect.objectContaining({
        scriptAssetId: "scene:血月街道",
        scriptAssetKind: "scene",
      }),
    });
  });

  it("selects a script prompt shot for the composition detail panel", () => {
    const { result, updateNodeData } = renderScriptWorkflow();

    act(() => {
      result.current.handleScriptPromptSelect(scriptNode(), "shot-2");
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      selectedScriptPromptShotId: "shot-2",
    });
  });

  it("starts one script prompt generation before marking it ready", () => {
    vi.useFakeTimers();
    const { result, updateNodeData } = renderScriptWorkflow();
    const node = scriptNode({
      scriptPromptStates: {
        "shot-1": "ready",
      },
    });

    act(() => {
      result.current.handleScriptPromptGenerate(node, "shot-2");
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      selectedScriptPromptShotId: "shot-2",
      scriptPromptStates: {
        "shot-1": "ready",
        "shot-2": "generating",
      },
      scriptPromptProgress: 3,
    });

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(updateNodeData).toHaveBeenLastCalledWith("script-1", {
      selectedScriptPromptShotId: "shot-2",
      scriptPromptStates: {
        "shot-1": "ready",
        "shot-2": "ready",
      },
      scriptPromptProgress: 100,
    });
    vi.useRealTimers();
  });

  it("starts every requested script prompt generation before marking them ready", () => {
    vi.useFakeTimers();
    const { result, updateNodeData } = renderScriptWorkflow();

    act(() => {
      result.current.handleScriptPromptsGenerateAll(scriptNode(), [
        "shot-1",
        "shot-2",
      ]);
    });

    expect(updateNodeData).toHaveBeenCalledWith("script-1", {
      scriptPromptStates: {
        "shot-1": "generating",
        "shot-2": "generating",
      },
      scriptPromptProgress: 3,
    });

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(updateNodeData).toHaveBeenLastCalledWith("script-1", {
      scriptPromptStates: {
        "shot-1": "ready",
        "shot-2": "ready",
      },
      scriptPromptProgress: 100,
    });
    vi.useRealTimers();
  });
});
