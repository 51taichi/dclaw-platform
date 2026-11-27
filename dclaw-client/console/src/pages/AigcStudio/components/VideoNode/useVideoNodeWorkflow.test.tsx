import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { useVideoNodeWorkflow } from "./useVideoNodeWorkflow";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const videoNode: AigcCanvasNode = {
  id: "video-1",
  type: "video_generate",
  position: { x: 620, y: 220 },
  data: {
    title: "视频节点",
    showTryOptions: true,
  },
};

const generatedVideoNode: AigcCanvasNode = {
  ...videoNode,
  data: {
    ...videoNode.data,
    aspectRatio: "16:9",
    videoDuration: 5,
    videoResolution: "720P",
    outputs: [
      {
        id: "video-output-1",
        kind: "video",
        name: "flying-sword.mp4",
        path: "aigc_studio/canvas-1/job-2/flying-sword.mp4",
        width: 1280,
        height: 720,
      },
    ],
  },
};

const uploadedVideoNode: AigcCanvasNode = {
  ...videoNode,
  data: {
    ...videoNode.data,
    previewKind: "uploaded_video",
    videoAssetName: "uploaded-demo.mp4",
    videoPreviewUrl: "blob:uploaded-demo",
    videoDuration: 5,
    videoResolution: "720P",
    aspectRatio: "16:9",
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
  provider_id: "volcengine",
  provider_name: "Volcengine",
  model_id: "seedance-2",
  model_name: "Seedance 2.0",
  capability: "text_to_video",
  source: "model_registry",
};

const uploadedAssetForFile = (file: File, index: number): AigcAsset => ({
  id: `uploaded-${index + 1}`,
  kind: file.type.startsWith("video/")
    ? "video"
    : file.type.startsWith("audio/")
    ? "audio"
    : "image",
  name: file.name,
  path: `oss://bucket/${file.name}`,
  url: `/api/aigc-studio/assets/uploaded-${index + 1}/file`,
  mime_type: file.type,
  created_at: "2026-06-12T00:00:00Z",
});

describe("useVideoNodeWorkflow", () => {
  it("creates a connected first-frame source node when image-to-video is selected", async () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const firstFrame = new File(["frame"], "first-frame.png", {
      type: "image/png",
    });

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(videoNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        modelOptions: [selectedModel],
        t,
        createAssetPreviewUrl: () => "blob:first-frame",
      }),
    );

    await act(async () => {
      await result.current.handleVideoTryUpload(videoNode, "first_frame", [
        firstFrame,
      ] as unknown as FileList);
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const sourceNode = updatedCanvas.nodes.find(
      (node) => node.type === "reference_asset",
    );
    const targetNode = updatedCanvas.nodes.find(
      (node) => node.id === "video-1",
    );

    expect(sourceNode).toMatchObject({
      type: "reference_asset",
      position: { x: 100, y: 220 },
      data: expect.objectContaining({
        assetName: "first-frame.png",
        assetPreviewUrl: "blob:first-frame",
        assetShape: "wide",
        previewKind: "uploaded_source",
      }),
    });
    expect(targetNode).toMatchObject({
      position: { x: 660, y: 220 },
      data: expect.objectContaining({
        activeVideoTab: "first_frame",
        aspectRatio: "16:9",
        referenceAssetName: "first-frame.png",
        referenceCount: 1,
        referencePreviewUrl: "blob:first-frame",
        referenceThumb: true,
        showTryOptions: false,
        videoDuration: 5,
        modelId: "seedance-2",
        modelLabel: "Seedance 2.0",
        providerId: "volcengine",
        videoModel: "Seedance 2.0",
        videoMode: "first_frame",
        videoResolution: "720P",
      }),
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: sourceNode?.id,
        target: "video-1",
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith("video-1");
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("creates connected composer reference sources for all-reference uploads", async () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const referenceFiles = [
      new File(["image"], "poster.png", { type: "image/png" }),
      new File(["video"], "clip.mp4", { type: "video/mp4" }),
      new File(["audio"], "voice.mp3", { type: "audio/mpeg" }),
    ];

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(videoNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        modelOptions: [selectedModel],
        t,
        createAssetPreviewUrl: (file) => `blob:${file.name}`,
      }),
    );

    await act(async () => {
      await result.current.handleVideoReferenceUpload(
        videoNode,
        "all_reference",
        referenceFiles as unknown as FileList,
      );
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const sourceNodes = updatedCanvas.nodes.filter(
      (node) => node.type === "reference_asset",
    );
    const targetNode = updatedCanvas.nodes.find(
      (node) => node.id === "video-1",
    );

    expect(sourceNodes).toHaveLength(3);
    expect(sourceNodes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: expect.objectContaining({
            assetKind: "image",
            assetName: "poster.png",
          }),
        }),
        expect.objectContaining({
          data: expect.objectContaining({
            assetKind: "video",
            assetName: "clip.mp4",
          }),
        }),
        expect.objectContaining({
          data: expect.objectContaining({
            assetKind: "audio",
            assetName: "voice.mp3",
          }),
        }),
      ]),
    );
    expect(targetNode).toMatchObject({
      data: expect.objectContaining({
        activeVideoTab: "all_reference",
        referenceAssetName: "poster.png, clip.mp4, voice.mp3",
        referenceCount: 3,
        referenceThumb: true,
        modelId: "seedance-2",
        modelLabel: "Seedance 2.0",
        providerId: "volcengine",
        videoModel: "Seedance 2.0",
        videoMode: "all_reference",
        videoReferenceAssets: expect.arrayContaining([
          expect.objectContaining({ name: "poster.png", kind: "image" }),
          expect.objectContaining({ name: "clip.mp4", kind: "video" }),
          expect.objectContaining({ name: "voice.mp3", kind: "audio" }),
        ]),
      }),
    });
    expect(updatedCanvas.edges).toHaveLength(3);
    expect(setSelectedNodeId).toHaveBeenCalledWith("video-1");
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("uploads composer reference files and stores stable asset URLs", async () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const referenceFiles = [
      new File(["image"], "poster.png", { type: "image/png" }),
      new File(["video"], "clip.mp4", { type: "video/mp4" }),
      new File(["audio"], "voice.mp3", { type: "audio/mpeg" }),
    ];
    const uploadAsset = vi.fn(async (file: File) =>
      uploadedAssetForFile(file, referenceFiles.indexOf(file)),
    );

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(videoNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
        createAssetPreviewUrl: (file) => `blob:${file.name}`,
        uploadAsset,
      }),
    );

    await act(async () => {
      await result.current.handleVideoReferenceUpload(
        videoNode,
        "all_reference",
        referenceFiles as unknown as FileList,
      );
    });

    expect(uploadAsset).toHaveBeenCalledTimes(3);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const sourceNodes = updatedCanvas.nodes.filter(
      (node) => node.type === "reference_asset",
    );
    const targetNode = updatedCanvas.nodes.find(
      (node) => node.id === "video-1",
    );

    expect(sourceNodes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: expect.objectContaining({
            assetName: "poster.png",
            assetPath: "oss://bucket/poster.png",
            assetPreviewUrl: "/api/aigc-studio/assets/uploaded-1/file",
            savedToAssets: true,
          }),
        }),
        expect.objectContaining({
          data: expect.objectContaining({
            assetName: "clip.mp4",
            assetPath: "oss://bucket/clip.mp4",
            assetPreviewUrl: "/api/aigc-studio/assets/uploaded-2/file",
            savedToAssets: true,
          }),
        }),
      ]),
    );
    const references = targetNode?.data.videoReferenceAssets as Array<{
      previewUrl: string;
    }>;
    expect(references.map((item) => item.previewUrl)).toEqual([
      "/api/aigc-studio/assets/uploaded-1/file",
      "/api/aigc-studio/assets/uploaded-2/file",
      "/api/aigc-studio/assets/uploaded-3/file",
    ]);
    expect(references.some((item) => item.previewUrl.startsWith("blob:"))).toBe(
      false,
    );
  });

  it("creates downstream nodes for generated video result actions", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(generatedVideoNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleGeneratedVideoAction(generatedVideoNode, "upscale");
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const upscaleNode = updatedCanvas.nodes.find(
      (node) => node.id !== "video-1",
    );

    expect(upscaleNode).toMatchObject({
      id: expect.stringMatching(/^video-upscale-/),
      type: "video_generate",
      position: { x: 1240, y: 220 },
      data: expect.objectContaining({
        title: "视频高清",
        videoMode: "video_upscale",
        referenceVideoNodeId: "video-1",
        referenceAssetName: "flying-sword.mp4",
        referencePreviewUrl: "aigc_studio/canvas-1/job-2/flying-sword.mp4",
      }),
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "video-1",
        target: upscaleNode?.id,
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith(upscaleNode?.id);
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("creates editable crop nodes for generated video result actions", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(generatedVideoNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleGeneratedVideoAction(generatedVideoNode, "crop");
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const cropNode = updatedCanvas.nodes.find((node) => node.id !== "video-1");

    expect(cropNode).toMatchObject({
      id: expect.stringMatching(/^video-crop-/),
      type: "video_generate",
      position: { x: 1240, y: 220 },
      data: expect.objectContaining({
        title: "视频裁剪",
        videoMode: "video_crop",
        cropMode: "free",
        referenceVideoNodeId: "video-1",
        referenceAssetName: "flying-sword.mp4",
        referencePreviewUrl: "aigc_studio/canvas-1/job-2/flying-sword.mp4",
      }),
    });
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "video-1",
        target: cropNode?.id,
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith(cropNode?.id);
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("uses uploaded video assets for video result actions", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(uploadedVideoNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleGeneratedVideoAction(
        uploadedVideoNode,
        "remove_subtitles",
      );
    });

    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0][0] as AigcCanvas;
    const subtitleRemovalNode = updatedCanvas.nodes.find(
      (node) => node.id !== "video-1",
    );

    expect(subtitleRemovalNode).toMatchObject({
      id: expect.stringMatching(/^video-subtitle-removal-/),
      type: "video_generate",
      data: expect.objectContaining({
        title: "智能去字幕",
        videoMode: "remove_subtitles",
        referenceVideoNodeId: "video-1",
        referenceAssetName: "uploaded-demo.mp4",
        referencePreviewUrl: "blob:uploaded-demo",
        sourceVideoName: "uploaded-demo.mp4",
        sourceVideoOutputPath: "blob:uploaded-demo",
      }),
    });
    expect(setSelectedNodeId).toHaveBeenCalledWith(subtitleRemovalNode?.id);
    expect(updateNodeData).not.toHaveBeenCalled();
  });

  it("marks generating video nodes as cancelled", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const generatingNode: AigcCanvasNode = {
      ...videoNode,
      data: {
        ...videoNode.data,
        job_status: "running",
        videoState: "generating",
        videoProgress: 18,
        outputs: [],
      },
    };

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(generatingNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleVideoCancelGeneration(generatingNode);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        job_error: "已取消生成",
        job_status: "cancelled",
        videoProgress: null,
        videoState: "failed",
      }),
    );
    expect(commitCanvas).not.toHaveBeenCalled();
    expect(setSelectedNodeId).not.toHaveBeenCalled();
  });

  it("retries failed video generation state", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const failedNode: AigcCanvasNode = {
      ...videoNode,
      data: {
        ...videoNode.data,
        error: "生成超时",
        job_error: "生成超时",
        job_status: "failed",
        videoProgress: null,
        videoState: "failed",
      },
    };

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(failedNode),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        t,
      }),
    );

    act(() => {
      result.current.handleVideoRetryGeneration(failedNode);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        error: null,
        job_error: null,
        job_status: "running",
        outputs: [],
        videoProgress: 1,
        videoState: "generating",
      }),
    );
    expect(commitCanvas).not.toHaveBeenCalled();
    expect(setSelectedNodeId).not.toHaveBeenCalled();
  });

  it("submits composer text with the selected video model metadata", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const nodeWithPrompt: AigcCanvasNode = {
      ...videoNode,
      data: {
        ...videoNode.data,
        composerText: "让产品在晨光里缓慢旋转",
      },
    };

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(nodeWithPrompt),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        modelOptions: [selectedModel],
        t,
      }),
    );

    act(() => {
      result.current.handleVideoComposerSubmit(nodeWithPrompt);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        text: "让产品在晨光里缓慢旋转",
        lastRunPrompt: "让产品在晨光里缓慢旋转",
        modelId: "seedance-2",
        modelLabel: "Seedance 2.0",
        providerId: "volcengine",
        showTryOptions: false,
        videoModel: "Seedance 2.0",
      }),
    );
    expect(commitCanvas).not.toHaveBeenCalled();
  });

  it("does not persist static video model labels when no generation model is available", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const nodeWithPrompt: AigcCanvasNode = {
      ...videoNode,
      data: {
        ...videoNode.data,
        composerText: "生成一个品牌开场镜头",
        modelLabel: "Seedance 2.0 VIP",
        videoModel: "Seedance 2.0 VIP",
      },
    };

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(nodeWithPrompt),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        modelOptions: [],
        t,
      }),
    );

    act(() => {
      result.current.handleVideoComposerSubmit(nodeWithPrompt);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        text: "生成一个品牌开场镜头",
        lastRunPrompt: "生成一个品牌开场镜头",
        modelId: undefined,
        modelLabel: undefined,
        providerId: undefined,
        videoModel: undefined,
      }),
    );
    expect(commitCanvas).not.toHaveBeenCalled();
  });

  it("runs the video node after composer submit using the saved prompt and model", () => {
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const updateNodeData = vi.fn();
    const runNode = vi.fn();
    const nodeWithPrompt: AigcCanvasNode = {
      ...videoNode,
      data: {
        ...videoNode.data,
        composerText: "全程使用第一视角构图，首帧从产品特写开始",
        aspectRatio: "9:16",
        videoResolution: "1080P",
        videoDuration: 8,
        videoAudio: false,
      },
    };

    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(nodeWithPrompt),
        commitCanvas,
        updateNodeData,
        setSelectedNodeId,
        modelOptions: [selectedModel],
        t,
        onRunNode: runNode,
      }),
    );

    act(() => {
      result.current.handleVideoComposerSubmit(nodeWithPrompt);
    });

    expect(runNode).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "video-1",
        data: expect.objectContaining({
          text: "全程使用第一视角构图，首帧从产品特写开始",
          lastRunPrompt: "全程使用第一视角构图，首帧从产品特写开始",
          modelId: "seedance-2",
          modelLabel: "Seedance 2.0",
          providerId: "volcengine",
          aspectRatio: "9:16",
          videoResolution: "1080P",
          videoDuration: 8,
          videoAudio: false,
        }),
      }),
    );
    expect(updateNodeData).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        text: "全程使用第一视角构图，首帧从产品特写开始",
        modelId: "seedance-2",
      }),
    );
  });

  it("preserves an exact reference-video workflow binding when submitting", () => {
    const updateNodeData = vi.fn();
    const runNode = vi.fn();
    const referenceModel = {
      ...selectedModel,
      model_id: "video-understanding-1",
      model_name: "Video Understanding",
      capability: "reference_video",
    };
    const nodeWithPrompt: AigcCanvasNode = {
      ...videoNode,
      data: {
        ...videoNode.data,
        composerText: "分析参考视频并生成延续镜头",
        workflowLogicalNodeId: "reference_clip",
        providerId: referenceModel.provider_id,
        modelId: referenceModel.model_id,
        modelCapability: referenceModel.capability,
      },
    };
    const { result } = renderHook(() =>
      useVideoNodeWorkflow({
        activeCanvas: canvasWithNode(nodeWithPrompt),
        commitCanvas: vi.fn(),
        updateNodeData,
        setSelectedNodeId: vi.fn(),
        modelOptions: [referenceModel],
        t,
        onRunNode: runNode,
      }),
    );

    act(() => result.current.handleVideoComposerSubmit(nodeWithPrompt));

    expect(runNode).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          providerId: referenceModel.provider_id,
          modelId: referenceModel.model_id,
          modelCapability: "reference_video",
        }),
      }),
    );
  });
});
