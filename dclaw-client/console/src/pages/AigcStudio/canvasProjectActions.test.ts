import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AigcCanvas, AigcJob } from "../../api/modules/aigcStudio";
import {
  createCanvasProject,
  deleteCanvasProject,
  selectCanvasProject,
} from "./canvasProjectActions";

const mockAigcStudioApi = vi.hoisted(() => ({
  createCanvas: vi.fn(),
  deleteCanvas: vi.fn(),
  listJobs: vi.fn(),
}));

vi.mock("../../api/modules/aigcStudio", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/modules/aigcStudio")>()),
  aigcStudioApi: mockAigcStudioApi,
}));

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const canvasFixture = (
  id: string,
  name = "Canvas",
  nodeId = `${id}-node`,
): AigcCanvas => ({
  id,
  name,
  nodes: [
    {
      id: nodeId,
      type: "prompt",
      position: { x: 80, y: 90 },
      data: { title: "Prompt" },
    },
  ],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 0.8 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

const jobFixture = (canvasId: string): AigcJob => ({
  id: "job-1",
  canvas_id: canvasId,
  node_id: "node-1",
  capability: "text_to_image",
  provider_id: "mock",
  model_id: "model",
  inputs: {},
  parameters: {},
  status: "queued",
  outputs: [],
  logs: [],
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasProjectActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("persists dirty canvas before creating a localized project", async () => {
    const activeCanvas = canvasFixture("canvas-1", "Dirty");
    const persistCanvas = vi.fn().mockResolvedValue(undefined);
    mockAigcStudioApi.createCanvas.mockResolvedValue(
      canvasFixture("canvas-2", "Untitled AIGC canvas"),
    );

    const result = await createCanvasProject({
      t,
      activeCanvas,
      savedCanvasSignature: "stale-signature",
      persistCanvas,
    });

    expect(persistCanvas).toHaveBeenCalledWith(activeCanvas);
    expect(mockAigcStudioApi.createCanvas).toHaveBeenCalledWith(
      expect.objectContaining({ name: "未命名 AIGC 画布" }),
    );
    expect(result.canvas.name).toBe("未命名 AIGC 画布");
    expect(result.signature).toContain("canvas-2");
  });

  it("persists dirty current canvas before selecting another project", async () => {
    const activeCanvas = canvasFixture("canvas-1", "Dirty");
    const targetCanvas = canvasFixture("canvas-2", "Next");
    const persistCanvas = vi.fn().mockResolvedValue(undefined);
    const jobs = [jobFixture("canvas-2")];
    mockAigcStudioApi.listJobs.mockResolvedValue({ jobs });

    const result = await selectCanvasProject({
      activeCanvas,
      targetCanvas,
      savedCanvasSignature: "stale-signature",
      persistCanvas,
    });

    expect(persistCanvas).toHaveBeenCalledWith(activeCanvas);
    expect(mockAigcStudioApi.listJobs).toHaveBeenCalledWith("canvas-2");
    expect(result.jobs).toEqual(jobs);
    expect(result.signature).toContain("canvas-2");
  });

  it("deletes a project and chooses the next active canvas", async () => {
    const first = canvasFixture("canvas-1", "First");
    const second = canvasFixture("canvas-2", "Second");
    mockAigcStudioApi.deleteCanvas.mockResolvedValue(undefined);

    const result = await deleteCanvasProject({
      canvas: first,
      activeCanvas: first,
      canvases: [first, second],
    });

    expect(mockAigcStudioApi.deleteCanvas).toHaveBeenCalledWith("canvas-1");
    expect(result.remainingCanvases).toEqual([second]);
    expect(result.nextCanvas).toEqual(second);
    expect(result.nextSignature).toContain("canvas-2");
  });
});
