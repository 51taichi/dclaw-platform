import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvas,
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import {
  imageModelForNode,
  imageModelOptionsFrom,
  imageNodeStateFromNode,
} from "./imageNodeState";
import { useImageNodeWorkflow } from "./useImageNodeWorkflow";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const imageNode: AigcCanvasNode = {
  id: "image-1",
  type: "image_generate",
  position: { x: 300, y: 120 },
  data: {
    title: "图片节点",
    imageMode: "blank",
    showTryOptions: true,
  },
};

const canvasWithNode = (node: AigcCanvasNode): AigcCanvas => ({
  id: "canvas-1",
  name: "测试画布",
  nodes: [node],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

const selectedModel: AigcCapabilityInfo = {
  provider_id: "modelscope",
  provider_name: "ModelScope",
  model_id: "qwen-image",
  model_name: "Qwen Image",
  capability: "text_to_image",
  source: "model_registry",
};

const selectedVideoModel: AigcCapabilityInfo = {
  provider_id: "volcengine",
  provider_name: "Volcengine",
  model_id: "seedance-2",
  model_name: "Seedance 2.0",
  capability: "text_to_video",
  source: "model_registry",
};

const selectedImageToVideoModel: AigcCapabilityInfo = {
  provider_id: "volcengine",
  provider_name: "Volcengine",
  model_id: "seedance-2-i2v",
  model_name: "Seedance 2.0 图生视频",
  capability: "image_to_video",
  source: "model_registry",
};

const mxapiImageModel: AigcCapabilityInfo = {
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: "gpt-image-2",
  model_name: "GPT Image 2 - MXAPI",
  capability: "image_edit",
  source: "model_registry",
};

describe("useImageNodeWorkflow", () => {
  it("derives image node UI state from empty, editing, generating, generated, and failed data", () => {
    expect(imageNodeStateFromNode(imageNode)).toBe("empty");
    expect(
      imageNodeStateFromNode({
        ...imageNode,
        data: {
          ...imageNode.data,
          composerText: "生成一张雪地里的老虎",
          showTryOptions: false,
        },
      }),
    ).toBe("editing");
    expect(
      imageNodeStateFromNode({
        ...imageNode,
        data: {
          ...imageNode.data,
          imageState: "generating",
          imageProgress: 2,
        },
      }),
    ).toBe("generating");
    expect(
      imageNodeStateFromNode({
        ...imageNode,
        data: {
          ...imageNode.data,
          outputs: [{ id: "asset-1", kind: "image", path: "image.png" }],
        },
      }),
    ).toBe("generated");
    expect(
      imageNodeStateFromNode({
        ...imageNode,
        data: {
          ...imageNode.data,
          job_status: "failed",
        },
      }),
    ).toBe("failed");
  });

  it("keeps image-to-video models out of image node model options", () => {
    expect(
      imageModelOptionsFrom([selectedImageToVideoModel, selectedModel]),
    ).toEqual([selectedModel]);
  });

  it("uploads the toolbar image as an image-to-image reference asset", async () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const file = new File(["image"], "reference.png", { type: "image/png" });
    const uploadAsset = vi.fn().mockResolvedValue({
      id: "asset-reference",
      kind: "image",
      name: "reference.png",
      path: "/stored/reference.png",
      url: "/api/user/aigc-studio/assets/asset-reference/file",
      mime_type: "image/png",
      created_at: "2026-06-26T00:00:00Z",
    });

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(imageNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
        createAssetPreviewUrl: () => "blob:local-reference",
        uploadAsset,
      }),
    );

    await act(async () => {
      await result.current.handleImageUpload(imageNode, file);
    });

    expect(uploadAsset).toHaveBeenCalledWith(file);
    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const sourceNode = updatedCanvas.nodes.find(
      (node) => node.type === "reference_asset",
    );
    const targetNode = updatedCanvas.nodes.find(
      (node) => node.id === "image-1",
    );

    expect(sourceNode).toMatchObject({
      type: "reference_asset",
      data: expect.objectContaining({
        assetKind: "image",
        assetName: "reference.png",
        assetPath: "/stored/reference.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/asset-reference/file",
        savedToAssets: true,
        previewKind: "uploaded_source",
      }),
    });
    expect(targetNode).toMatchObject({
      data: expect.objectContaining({
        imageMode: "image_to_image",
        imageState: "editing",
        referenceThumb: true,
        referenceAssetName: "reference.png",
        referencePreviewUrl:
          "/api/user/aigc-studio/assets/asset-reference/file",
      }),
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: sourceNode?.id,
        target: "image-1",
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith("image-1");
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("deduplicates image model options by provider and model", () => {
    const editCapability = {
      ...selectedModel,
      capability: "image_edit",
    };
    const imageToImageCapability = {
      ...selectedModel,
      capability: "image_to_image",
    };

    expect(
      imageModelOptionsFrom([
        editCapability,
        selectedVideoModel,
        selectedModel,
        imageToImageCapability,
      ]),
    ).toEqual([selectedModel]);
  });

  it("preserves the bound capability for a workflow image model", () => {
    const textCapability = {
      ...mxapiImageModel,
      capability: "text_to_image",
    };
    const workflowNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        workflowLogicalNodeId: "repair_image",
        providerId: mxapiImageModel.provider_id,
        modelId: mxapiImageModel.model_id,
        modelLabel: mxapiImageModel.model_name,
        modelCapability: "image_edit",
        imageMode: "image_to_image",
      },
    };

    expect(
      imageModelForNode(workflowNode, null, [textCapability, mxapiImageModel]),
    ).toBe(mxapiImageModel);
  });

  it("does not treat an untyped saved video model as the image node model", () => {
    expect(
      imageModelForNode(
        {
          ...imageNode,
          data: {
            ...imageNode.data,
            providerId: selectedVideoModel.provider_id,
            modelId: selectedVideoModel.model_id,
            modelLabel: selectedVideoModel.model_name,
          },
        },
        null,
        [selectedVideoModel, selectedModel],
      ),
    ).toBe(selectedModel);
  });

  it("preserves a removed saved image model until migration is confirmed", () => {
    const removedModelNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        providerId: "volcengine",
        modelId: "removed-seedream",
        modelLabel: "Removed Seedream",
      },
    };

    expect(imageModelForNode(removedModelNode, null, [selectedModel])).toEqual(
      expect.objectContaining({
        provider_id: "volcengine",
        model_id: "removed-seedream",
      }),
    );
  });

  it("uploads image-to-image references before creating the connected source node", async () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const file = new File(["image"], "reference.png", { type: "image/png" });
    const uploadAsset = vi.fn().mockResolvedValue({
      id: "asset-i2i-reference",
      kind: "image",
      name: "reference.png",
      path: "/stored/reference.png",
      url: "/api/user/aigc-studio/assets/asset-i2i-reference/file",
      mime_type: "image/png",
      created_at: "2026-06-26T00:00:00Z",
    });

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(imageNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
        createAssetPreviewUrl: () => "blob:test-image",
        uploadAsset,
      }),
    );

    await act(async () => {
      await result.current.handleImageToImageUpload(imageNode, file);
    });

    expect(uploadAsset).toHaveBeenCalledWith(file);
    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const sourceNode = updatedCanvas.nodes.find(
      (node) => node.type === "reference_asset",
    );
    const targetNode = updatedCanvas.nodes.find(
      (node) => node.id === "image-1",
    );

    expect(sourceNode).toMatchObject({
      type: "reference_asset",
      position: { x: 300, y: 124 },
      data: expect.objectContaining({
        assetName: "reference.png",
        assetPath: "/stored/reference.png",
        assetPreviewUrl:
          "/api/user/aigc-studio/assets/asset-i2i-reference/file",
        savedToAssets: true,
        previewKind: "uploaded_source",
      }),
    });
    expect(targetNode).toMatchObject({
      position: { x: 730, y: 142 },
      data: expect.objectContaining({
        imageMode: "image_to_image",
        referenceThumb: true,
        referenceAssetName: "reference.png",
        referencePreviewUrl:
          "/api/user/aigc-studio/assets/asset-i2i-reference/file",
      }),
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: sourceNode?.id,
        target: "image-1",
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith("image-1");
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("creates a connected capture group from a generated panorama image", () => {
    const generatedNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        title: "全景图片",
        imageMode: "panorama",
        panoramaMode: true,
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
        outputs: [
          {
            id: "asset-panorama",
            kind: "image",
            name: "panorama.png",
            path: "aigc_studio/canvas-1/job-2/panorama.png",
            width: 2048,
            height: 1024,
          },
        ],
      },
    };
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(generatedNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
        createAssetPreviewUrl: () => "blob:test-image",
      }),
    );

    act(() => {
      result.current.handleImageCaptureGroup(generatedNode, "four");
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const captureNode = updatedCanvas.nodes.find(
      (node) => node.data.previewKind === "image_capture_group",
    );

    expect(captureNode).toMatchObject({
      type: "reference_asset",
      position: { x: 920, y: 120 },
      data: expect.objectContaining({
        title: "全景截图组 (4张)",
        captureMode: "four",
        captureCount: 4,
        sourceImageNodeId: "image-1",
        sourceImageOutputPath: "aigc_studio/canvas-1/job-2/panorama.png",
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
      }),
    });
    expect(captureNode?.data.captureFrames).toEqual([
      expect.objectContaining({
        label: "全景截图-前方",
        yaw: 0,
        pitch: 0,
        zoom: 1,
      }),
      expect.objectContaining({
        label: "全景截图-左侧",
        yaw: 90,
        pitch: 0,
        zoom: 1,
      }),
      expect.objectContaining({
        label: "全景截图-后方",
        yaw: 180,
        pitch: 0,
        zoom: 1,
      }),
      expect.objectContaining({
        label: "全景截图-右侧",
        yaw: 270,
        pitch: 0,
        zoom: 1,
      }),
    ]);
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "image-1",
        target: captureNode?.id,
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith(captureNode?.id);
  });

  it("adds camera pose metadata to current and twelve-view capture frames", () => {
    const generatedNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        imageMode: "panorama",
        panoramaMode: true,
        outputs: [
          {
            id: "asset-panorama",
            kind: "image",
            name: "panorama.png",
            path: "aigc_studio/canvas-1/job-2/panorama.png",
          },
        ],
      },
    };
    const commitCanvas = vi.fn();

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(generatedNode),
        commitCanvas,
        updateNodeData: vi.fn(),
        setSelectedNodeId: vi.fn(),
        t,
      }),
    );

    act(() => {
      result.current.handleImageCaptureGroup(generatedNode, "current");
    });
    act(() => {
      result.current.handleImageCaptureGroup(generatedNode, "twelve");
    });

    const currentCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const currentCaptureNode = currentCanvas.nodes.find(
      (node) => node.data.captureMode === "current",
    );
    expect(currentCaptureNode?.data.captureFrames).toEqual([
      expect.objectContaining({
        label: "全景截图-当前视角",
        yaw: 0,
        pitch: 0,
        zoom: 1,
      }),
    ]);

    const twelveCanvas = commitCanvas.mock.calls[1][0] as AigcCanvas;
    const twelveCaptureNode = twelveCanvas.nodes.find(
      (node) => node.data.captureMode === "twelve",
    );
    const twelveFrames = twelveCaptureNode?.data.captureFrames as Array<
      Record<string, unknown>
    >;
    expect(twelveFrames).toHaveLength(12);
    expect(twelveFrames[0]).toMatchObject({
      label: "全景截图-逆时针0°",
      yaw: 0,
      pitch: 0,
      zoom: 1,
    });
    expect(twelveFrames[11]).toMatchObject({
      label: "全景截图-逆时针330°",
      yaw: 330,
      pitch: 0,
      zoom: 1,
    });
  });

  it("sends a capture group into a connected image editing node", () => {
    const captureNode: AigcCanvasNode = {
      id: "capture-four-1",
      type: "reference_asset",
      position: { x: 920, y: 120 },
      data: {
        title: "全景截图组 (4张)",
        previewKind: "image_capture_group",
        captureMode: "four",
        captureCount: 4,
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
        sourceImageOutputPath: "aigc_studio/canvas-1/job-2/panorama.png",
        captureFrames: [
          {
            id: "four-1",
            label: "全景截图-前方",
            assetPreviewUrl: "aigc_studio/canvas-1/job-2/panorama.png",
          },
        ],
      },
    };
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(captureNode),
        commitCanvas,
        updateNodeData: vi.fn(),
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleImageCaptureGroupSendToImage(captureNode);
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const imageTarget = updatedCanvas.nodes.find(
      (node) => node.type === "image_generate",
    );

    expect(imageTarget).toMatchObject({
      type: "image_generate",
      position: { x: 1540, y: 142 },
      data: expect.objectContaining({
        title: "图片节点",
        imageMode: "image_to_image",
        imageState: "editing",
        showTryOptions: false,
        referenceThumb: true,
        referenceAssetName: "全景截图组 (4张)",
        referencePreviewUrl: "aigc_studio/canvas-1/job-2/panorama.png",
        referenceCaptureGroupId: "capture-four-1",
        referenceCaptureCount: 4,
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
      }),
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "capture-four-1",
        target: imageTarget?.id,
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith(imageTarget?.id);
  });

  it("selects a capture frame and uses it for downstream image editing", () => {
    const captureNode: AigcCanvasNode = {
      id: "director-capture-group-1",
      type: "reference_asset",
      position: { x: 920, y: 120 },
      data: {
        title: "导演台截图组",
        previewKind: "image_capture_group",
        captureMode: "director_stage",
        captureCount: 2,
        selectedCaptureId: "capture-2",
        captureFrames: [
          {
            id: "capture-1",
            label: "机位01",
            assetId: "asset-1",
            assetName: "机位01.png",
            assetPath: "oss://bucket/asset-1.png",
            assetMimeType: "image/png",
            assetPreviewUrl: "/assets/asset-1/file",
          },
          {
            id: "capture-2",
            label: "机位02",
            assetId: "asset-2",
            assetName: "机位02.png",
            assetPath: "oss://bucket/asset-2.png",
            assetMimeType: "image/png",
            assetPreviewUrl: "/assets/asset-2/file",
          },
        ],
      },
    };
    const commitCanvas = vi.fn();
    const updateNodeData = vi.fn();
    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(captureNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId: vi.fn(),
        t,
      }),
    );

    act(() => {
      result.current.handleImageCaptureGroupSelect(captureNode, "capture-1");
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "director-capture-group-1",
      expect.objectContaining({
        selectedCaptureId: "capture-1",
        assetId: "asset-1",
        assetName: "机位01.png",
        assetPreviewUrl: "/assets/asset-1/file",
        referenceAssetId: "asset-1",
        referencePreviewUrl: "/assets/asset-1/file",
      }),
    );

    act(() => {
      result.current.handleImageCaptureGroupSendToImage(captureNode);
    });

    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const imageTarget = updatedCanvas.nodes.find(
      (node) => node.type === "image_generate",
    );
    expect(imageTarget?.data).toEqual(
      expect.objectContaining({
        referenceAssetName: "机位02.png",
        referencePreviewUrl: "/assets/asset-2/file",
        referenceCaptureGroupId: "director-capture-group-1",
      }),
    );
  });

  it("carries image tool presets from generated results into connected image editing nodes", () => {
    const generatedNode: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        imageState: "generated",
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
        outputs: [
          {
            id: "asset-1",
            kind: "image",
            name: "result.png",
            path: "aigc_studio/canvas-1/job-2/result.png",
          },
        ],
      },
    };
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(generatedNode),
        commitCanvas,
        updateNodeData: vi.fn(),
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleGeneratedImageSendToImage(generatedNode);
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const imageTarget = updatedCanvas.nodes.find(
      (node) => node.type === "image_generate" && node.id !== generatedNode.id,
    );

    expect(imageTarget).toMatchObject({
      type: "image_generate",
      data: expect.objectContaining({
        imageMode: "image_to_image",
        referenceImageNodeId: "image-1",
        referenceAssetName: "result.png",
        referencePreviewUrl: "aigc_studio/canvas-1/job-2/result.png",
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
      }),
    });
    expect(setSelectedNodeId).toHaveBeenCalledWith(imageTarget?.id);
  });

  it("falls back to an image-capable model when the selected model is not for images", () => {
    const updateNodeData = vi.fn();
    const nodeWithPrompt: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        composerText: "生成一张雪夜中的城市全景",
      },
    };

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(nodeWithPrompt),
        commitCanvas: vi.fn(),
        updateNodeData,
        setSelectedNodeId: vi.fn(),
        modelOptions: [selectedVideoModel, selectedModel],
        t,
      }),
    );

    act(() => {
      result.current.handleImageComposerSubmit(nodeWithPrompt);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        text: "生成一张雪夜中的城市全景",
        lastRunPrompt: "生成一张雪夜中的城市全景",
        modelId: "qwen-image",
        modelLabel: "Qwen Image",
        providerId: "modelscope",
      }),
    );
  });

  it("stores GPT Image 2 model labels without the relay suffix", () => {
    const updateNodeData = vi.fn();
    const nodeWithPrompt: AigcCanvasNode = {
      ...imageNode,
      data: {
        ...imageNode.data,
        composerText: "把包装做成高端海报",
      },
    };

    const { result } = renderHook(() =>
      useImageNodeWorkflow({
        activeCanvas: canvasWithNode(nodeWithPrompt),
        commitCanvas: vi.fn(),
        updateNodeData,
        setSelectedNodeId: vi.fn(),
        modelOptions: [mxapiImageModel],
        t,
      }),
    );

    act(() => {
      result.current.handleImageComposerSubmit(nodeWithPrompt);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        modelId: "gpt-image-2",
        modelLabel: "GPT Image 2",
        providerId: "mxapi",
      }),
    );
  });
});
