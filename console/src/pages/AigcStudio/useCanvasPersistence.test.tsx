import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AigcCanvas,
  AigcCapabilityInfo,
} from "../../api/modules/aigcStudio";
import { useCanvasPersistence } from "./useCanvasPersistence";
import { canvasSignature } from "./canvasAssetFactory";

const mockAigcStudioApi = vi.hoisted(() => ({
  listCapabilities: vi.fn(),
  listCanvases: vi.fn(),
  createCanvas: vi.fn(),
  saveCanvas: vi.fn(),
  listJobs: vi.fn(),
}));

vi.mock("../../api/modules/aigcStudio", () => ({
  aigcStudioApi: mockAigcStudioApi,
}));

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
  viewport: { x: 10, y: 20, zoom: 0.75 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useCanvasPersistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("loads capabilities, localizes legacy canvases, and tracks saved state", async () => {
    const setViewportScale = vi.fn();
    const capabilities: AigcCapabilityInfo[] = [
      {
        provider_id: "mock",
        provider_name: "Mock",
        model_id: "text-model",
        model_name: "Text Model",
        capability: "text_to_image",
        source: "model_registry",
      },
    ];
    mockAigcStudioApi.listCapabilities.mockResolvedValue({ capabilities });
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [canvasFixture()],
    });
    mockAigcStudioApi.listJobs.mockResolvedValue({ jobs: [] });

    const { result } = renderHook(() =>
      useCanvasPersistence({ t, onViewportScaleChange: setViewportScale }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.capabilities).toEqual(capabilities);
    expect(result.current.canvases).toHaveLength(1);
    expect(result.current.activeCanvas?.name).toBe("未命名 AIGC 画布");
    expect(result.current.activeCanvas?.nodes[0].data.title).toBe("营销提示词");
    expect(result.current.autoSaveStatus).toBe("saved");
    expect(setViewportScale).toHaveBeenCalledWith(0.75);
    expect(mockAigcStudioApi.saveCanvas).not.toHaveBeenCalled();
  });

  it("does not auto-create a starter project when the account has no canvases", async () => {
    const setViewportScale = vi.fn();
    mockAigcStudioApi.listCapabilities.mockResolvedValue({ capabilities: [] });
    mockAigcStudioApi.listCanvases.mockResolvedValue({ canvases: [] });

    const { result } = renderHook(() =>
      useCanvasPersistence({ t, onViewportScaleChange: setViewportScale }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.canvases).toEqual([]);
    expect(result.current.activeCanvas).toBeNull();
    expect(result.current.jobs).toEqual([]);
    expect(mockAigcStudioApi.createCanvas).not.toHaveBeenCalled();
    expect(setViewportScale).not.toHaveBeenCalled();
  });

  it("activates the exact bound canvas and loads only its jobs", async () => {
    const setViewportScale = vi.fn();
    const first = canvasFixture();
    const second = { ...canvasFixture(), id: "canvas-2", name: "Bound canvas" };
    mockAigcStudioApi.listCapabilities.mockResolvedValue({ capabilities: [] });
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [first, second],
    });
    mockAigcStudioApi.listJobs
      .mockResolvedValueOnce({ jobs: [] })
      .mockResolvedValueOnce({ jobs: [{ id: "job-for-canvas-2" }] });

    const { result } = renderHook(() =>
      useCanvasPersistence({ t, onViewportScaleChange: setViewportScale }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.activateCanvasById("canvas-2");
    });

    expect(result.current.activeCanvas?.id).toBe("canvas-2");
    expect(mockAigcStudioApi.listJobs).toHaveBeenLastCalledWith("canvas-2");
    expect(result.current.jobs).toEqual([{ id: "job-for-canvas-2" }]);
  });

  it("coalesces auto-save requests while a canvas save is still in flight", async () => {
    vi.useFakeTimers();
    const firstSave = deferred<AigcCanvas>();
    mockAigcStudioApi.saveCanvas
      .mockReturnValueOnce(firstSave.promise)
      .mockImplementation(async (id, body) => ({
        id,
        ...body,
        created_at: "2026-06-12T00:00:00Z",
        updated_at: "2026-06-12T00:00:01Z",
      }));

    const { result } = renderHook(() =>
      useCanvasPersistence({
        t,
        onViewportScaleChange: vi.fn(),
        autoLoad: false,
        autoSaveDelay: 10,
      }),
    );

    const saved = canvasFixture();
    const firstChange = { ...saved, name: "First change" };
    const latestChange = { ...saved, name: "Latest change" };

    act(() => {
      result.current.setLoading(false);
      result.current.savedCanvasSignatureRef.current = canvasSignature(saved);
      result.current.setActiveCanvas(saved);
    });

    act(() => {
      result.current.setActiveCanvas(firstChange);
    });
    await act(async () => {
      vi.advanceTimersByTime(10);
      await Promise.resolve();
    });
    expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setActiveCanvas(latestChange);
    });
    await act(async () => {
      vi.advanceTimersByTime(10);
      await Promise.resolve();
    });
    expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledTimes(1);

    await act(async () => {
      firstSave.resolve(firstChange);
      await firstSave.promise;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledTimes(2);
    expect(mockAigcStudioApi.saveCanvas).toHaveBeenLastCalledWith(
      "canvas-1",
      expect.objectContaining({ name: "Latest change" }),
    );
    expect(result.current.autoSaveStatus).toBe("saved");
  });
});
