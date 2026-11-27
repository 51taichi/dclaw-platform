import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import { enabledPortTypesForNode } from "../../domain/componentRegistry";
import { DIRECTOR_STAGE_MODEL_ATTRIBUTIONS } from "./directorStageTypes";
import { useDirectorStageWorkflow } from "./useDirectorStageWorkflow";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const stageNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "stage-1",
  type: "director_stage",
  position: { x: 320, y: 160 },
  data,
});

const canvas = (nodes: AigcCanvasNode[] = [stageNode()]): AigcCanvas => ({
  id: "canvas-1",
  name: "画布 1",
  nodes,
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-07-09T00:00:00.000Z",
  updated_at: "2026-07-09T00:00:00.000Z",
});

const uploadedAsset: AigcAsset = {
  id: "asset-1",
  kind: "image",
  name: "机位01.png",
  path: "oss://bucket/aigc_studio/uploads/asset-1.png",
  url: "/api/user/aigc-studio/assets/asset-1/file",
  mime_type: "image/png",
  created_at: "2026-07-09T00:00:00.000Z",
  meta: {},
};

const uploadedModelAsset: AigcAsset = {
  id: "model-asset-1",
  kind: "file",
  name: "hero.glb",
  path: "oss://bucket/aigc_studio/uploads/model-asset-1.glb",
  url: "/api/user/aigc-studio/assets/model-asset-1/file",
  mime_type: "model/gltf-binary",
  created_at: "2026-07-13T00:00:00.000Z",
  meta: {},
};

describe("useDirectorStageWorkflow", () => {
  it("saves director stage project data onto the current node", () => {
    const updateNodeData = vi.fn();
    const { result } = renderHook(() =>
      useDirectorStageWorkflow({
        activeCanvas: canvas(),
        commitCanvas: vi.fn(),
        setSelectedNodeId: vi.fn(),
        updateNodeData,
        uploadAsset: vi.fn(),
        t,
      }),
    );
    const project = {
      version: 1 as const,
      scene: { backgroundColor: "#101114" },
      objects: [
        {
          id: "character-1",
          kind: "character" as const,
          name: "角色01",
          position: [0, 0, 0] as [number, number, number],
          rotation: [0, 0, 0] as [number, number, number],
          scale: [1, 1, 1] as [number, number, number],
          modelId: "ue-mannequin-retopology",
        },
      ],
      cameras: [
        {
          id: "camera-1",
          name: "机位01",
          position: [4, 3, 6] as [number, number, number],
          target: [0, 1, 0] as [number, number, number],
          fov: 45,
        },
      ],
    };

    act(() => {
      result.current.handleSaveProject(stageNode(), project);
    });

    expect(updateNodeData).toHaveBeenCalledWith("stage-1", {
      directorStageError: null,
      directorStageProject: project,
      modelAttributions: DIRECTOR_STAGE_MODEL_ATTRIBUTIONS,
    });
  });

  it("uploads a camera capture and creates a linked reference asset node", async () => {
    const node = stageNode();
    const activeCanvas = canvas([node]);
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const uploadAsset = vi.fn(async () => uploadedAsset);
    const { result } = renderHook(() =>
      useDirectorStageWorkflow({
        activeCanvas,
        commitCanvas,
        setSelectedNodeId,
        updateNodeData: vi.fn(),
        uploadAsset,
        t,
      }),
    );

    await act(async () => {
      await result.current.handleCapture(node, {
        dataUrl: "data:image/png;base64,aGVsbG8=",
        fileName: "机位01.png",
        project: {
          version: 1,
          objects: [],
          cameras: [
            {
              id: "camera-1",
              name: "机位01",
              position: [4, 3, 6],
              target: [0, 1, 0],
              fov: 45,
            },
          ],
        },
      });
    });

    expect(uploadAsset).toHaveBeenCalledTimes(1);
    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0]![0] as AigcCanvas;
    const updatedStage = updatedCanvas.nodes.find(
      (item) => item.id === "stage-1",
    );
    const captureNode = updatedCanvas.nodes.find(
      (item) => item.id !== "stage-1",
    );

    expect(updatedStage?.data).toEqual(
      expect.objectContaining({
        previewAssetId: "asset-1",
        previewUrl: "/api/user/aigc-studio/assets/asset-1/file",
      }),
    );
    expect(updatedStage?.data.directorStageCaptures).toEqual([
      expect.objectContaining({
        assetId: "asset-1",
        name: "机位01.png",
        previewUrl: "/api/user/aigc-studio/assets/asset-1/file",
      }),
    ]);
    expect(captureNode).toEqual(
      expect.objectContaining({
        type: "reference_asset",
        data: expect.objectContaining({
          assetKind: "image",
          assetName: "机位01.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
          previewKind: "uploaded_source",
          sourceDirectorStageNodeId: "stage-1",
        }),
      }),
    );
    expect(
      enabledPortTypesForNode(captureNode as AigcCanvasNode, "right"),
    ).toEqual(expect.arrayContaining(["image_generate", "video_generate"]));
    expect(updatedCanvas.edges).toEqual([
      expect.objectContaining({
        source: "stage-1",
        target: captureNode?.id,
      }),
    ]);
    expect(setSelectedNodeId).toHaveBeenCalledWith(captureNode?.id);
  });

  it("uploads a GLB model and returns a reusable director stage asset reference", async () => {
    const updateNodeData = vi.fn();
    const uploadAsset = vi.fn(async () => uploadedModelAsset);
    const { result } = renderHook(() =>
      useDirectorStageWorkflow({
        activeCanvas: canvas(),
        commitCanvas: vi.fn(),
        setSelectedNodeId: vi.fn(),
        updateNodeData,
        uploadAsset,
        t,
      }),
    );
    const file = new File(["glb-model"], "hero.glb", {
      type: "model/gltf-binary",
    });
    let uploadResult: Awaited<
      ReturnType<typeof result.current.handleUploadModel>
    > | null = null;

    await act(async () => {
      uploadResult = await result.current.handleUploadModel(
        stageNode(),
        file,
        "character",
      );
    });

    expect(uploadAsset).toHaveBeenCalledWith(file);
    expect(uploadResult).toEqual({
      ok: true,
      model: expect.objectContaining({
        id: "uploaded-model-model-asset-1",
        assetId: "model-asset-1",
        kind: "character",
        name: "hero",
        fileName: "hero.glb",
        url: "/api/user/aigc-studio/assets/model-asset-1/file",
        size: file.size,
      }),
    });
    expect(updateNodeData).toHaveBeenCalledWith("stage-1", {
      directorStageError: null,
    });
  });

  it("rejects dependent GLTF files before upload", async () => {
    const updateNodeData = vi.fn();
    const uploadAsset = vi.fn();
    const { result } = renderHook(() =>
      useDirectorStageWorkflow({
        activeCanvas: canvas(),
        commitCanvas: vi.fn(),
        setSelectedNodeId: vi.fn(),
        updateNodeData,
        uploadAsset,
        t,
      }),
    );
    const file = new File(["{}"], "scene.gltf", {
      type: "model/gltf+json",
    });

    let uploadResult: Awaited<
      ReturnType<typeof result.current.handleUploadModel>
    > | null = null;
    await act(async () => {
      uploadResult = await result.current.handleUploadModel(
        stageNode(),
        file,
        "prop",
      );
    });

    expect(uploadAsset).not.toHaveBeenCalled();
    expect(uploadResult).toEqual({
      ok: false,
      error: "导演台当前仅支持单文件 GLB 模型",
    });
    expect(updateNodeData).toHaveBeenCalledWith("stage-1", {
      directorStageError: "导演台当前仅支持单文件 GLB 模型",
    });
  });

  it("uploads all camera captures into one linked capture group", async () => {
    const node = stageNode();
    const activeCanvas = canvas([node]);
    const commitCanvas = vi.fn();
    const setSelectedNodeId = vi.fn();
    const secondAsset: AigcAsset = {
      ...uploadedAsset,
      id: "asset-2",
      name: "机位02.png",
      path: "oss://bucket/aigc_studio/uploads/asset-2.png",
      url: "/api/user/aigc-studio/assets/asset-2/file",
    };
    const uploadAsset = vi
      .fn()
      .mockResolvedValueOnce(uploadedAsset)
      .mockResolvedValueOnce(secondAsset);
    const { result } = renderHook(() =>
      useDirectorStageWorkflow({
        activeCanvas,
        commitCanvas,
        setSelectedNodeId,
        updateNodeData: vi.fn(),
        uploadAsset,
        t,
      }),
    );
    const project = {
      version: 1 as const,
      objects: [],
      cameras: [
        {
          id: "camera-1",
          name: "机位01",
          position: [4, 3, 6] as [number, number, number],
          target: [0, 1, 0] as [number, number, number],
          fov: 45,
        },
        {
          id: "camera-2",
          name: "机位02",
          position: [6, 4, 3] as [number, number, number],
          target: [0, 1, 0] as [number, number, number],
          fov: 50,
        },
      ],
      activeCameraId: "camera-2",
    };

    await act(async () => {
      await result.current.handleCaptureBatch(node, [
        {
          dataUrl: "data:image/png;base64,aGVsbG8=",
          fileName: "机位01.png",
          project,
        },
        {
          dataUrl: "data:image/png;base64,d29ybGQ=",
          fileName: "机位02.png",
          project,
        },
      ]);
    });

    expect(uploadAsset).toHaveBeenCalledTimes(2);
    expect(commitCanvas).toHaveBeenCalledTimes(1);
    const updatedCanvas = commitCanvas.mock.calls[0]![0] as AigcCanvas;
    const updatedStage = updatedCanvas.nodes.find(
      (item) => item.id === "stage-1",
    );
    const captureNodes = updatedCanvas.nodes.filter(
      (item) => item.type === "reference_asset",
    );

    expect(updatedStage?.data.directorStageCaptures).toEqual([
      expect.objectContaining({ assetId: "asset-1", name: "机位01.png" }),
      expect.objectContaining({ assetId: "asset-2", name: "机位02.png" }),
    ]);
    expect(updatedStage?.data).toEqual(
      expect.objectContaining({
        previewAssetId: "asset-2",
        previewUrl: "/api/user/aigc-studio/assets/asset-2/file",
      }),
    );
    expect(captureNodes).toHaveLength(1);
    expect(captureNodes[0]).toEqual(
      expect.objectContaining({
        data: expect.objectContaining({
          title: "导演台截图组",
          previewKind: "image_capture_group",
          captureMode: "director_stage",
          captureCount: 2,
          selectedCaptureId: "director-stage-capture-asset-1",
          assetName: "机位01.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
          sourceDirectorStageNodeId: "stage-1",
        }),
      }),
    );
    expect(captureNodes[0]?.data.captureFrames).toEqual([
      expect.objectContaining({
        id: "director-stage-capture-asset-1",
        label: "机位01",
        assetId: "asset-1",
        assetName: "机位01.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
        cameraId: "camera-1",
        fov: 45,
      }),
      expect.objectContaining({
        id: "director-stage-capture-asset-2",
        label: "机位02",
        assetId: "asset-2",
        assetName: "机位02.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/asset-2/file",
        cameraId: "camera-2",
        fov: 50,
      }),
    ]);
    expect(updatedCanvas.edges).toHaveLength(1);
    expect(setSelectedNodeId).toHaveBeenCalledWith(captureNodes[0]?.id);
  });

  it("keeps the editor state and records an error when capture upload fails", async () => {
    const updateNodeData = vi.fn();
    const commitCanvas = vi.fn();
    const { result } = renderHook(() =>
      useDirectorStageWorkflow({
        activeCanvas: canvas(),
        commitCanvas,
        setSelectedNodeId: vi.fn(),
        updateNodeData,
        uploadAsset: vi.fn(async () => {
          throw new Error("upload failed");
        }),
        t,
      }),
    );

    await act(async () => {
      await result.current.handleCapture(stageNode(), {
        dataUrl: "data:image/png;base64,aGVsbG8=",
        fileName: "机位01.png",
        project: { version: 1, objects: [], cameras: [] },
      });
    });

    expect(commitCanvas).not.toHaveBeenCalled();
    expect(updateNodeData).toHaveBeenCalledWith(
      "stage-1",
      expect.objectContaining({
        directorStageError: "upload failed",
        directorStageProject: { version: 1, objects: [], cameras: [] },
        modelAttributions: expect.any(Array),
      }),
    );
  });
});
