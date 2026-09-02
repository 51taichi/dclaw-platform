import { describe, expect, it } from "vitest";

import type { AigcCanvas, AigcJob } from "../../../../api/modules/aigcStudio";
import type { BoundAigcTask } from "../../../../api/modules/superExpertPlatform";
import { getAigcGuideStepCompletion } from "./guideStepCompletion";

const task: BoundAigcTask = {
  binding: {
    installation_id: "installation-1",
    conversation_id: "conversation-1",
    material_task_id: "task-1",
    canvas_id: "canvas-1",
    node_id: "node-1",
  },
  status: "IN_PROGRESS",
  operation_id: "aigc.text_to_video.create",
  operation_version: "1",
  operation_arguments: {
    prompt: "exact prompt",
    model_id: "model-1",
    aspect_ratio: "9:16",
    duration_seconds: 5,
  },
};

const canvas = (data: Record<string, unknown>): AigcCanvas => ({
  id: "canvas-1",
  name: "project",
  nodes: [{ id: "node-1", type: "video_generate", position: { x: 0, y: 0 }, data }],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-09-02T00:00:00Z",
  updated_at: "2026-09-02T00:00:00Z",
});

describe("getAigcGuideStepCompletion", () => {
  it("verifies each pre-generation step against the exact bound canvas and node", () => {
    expect(
      getAigcGuideStepCompletion({
        task,
        activeCanvas: canvas({
          text: "exact prompt",
          modelId: "model-1",
          aspectRatio: "9:16",
          videoDuration: 5,
        }),
        jobs: [],
      }),
    ).toMatchObject({
      "open-studio": true,
      "create-project": true,
      "add-video-node": true,
      "enter-prompt": true,
      "select-model": true,
      "select-ratio": true,
      "select-duration": true,
      "generate-video": false,
      "verify-result": false,
    });
  });

  it("requires a bound generation job and output before the final steps pass", () => {
    const job = {
      id: "job-1",
      canvas_id: "canvas-1",
      node_id: "node-1",
      status: "succeeded",
      outputs: [{ id: "asset-1" }],
    } as AigcJob;
    const result = getAigcGuideStepCompletion({
      task,
      activeCanvas: canvas({ outputs: [{ id: "asset-1" }] }),
      jobs: [job],
    });
    expect(result["generate-video"]).toBe(true);
    expect(result["verify-result"]).toBe(true);
  });

  it("never accepts evidence from another canvas", () => {
    const otherCanvas = { ...canvas({ text: "exact prompt" }), id: "canvas-other" };
    expect(
      Object.values(
        getAigcGuideStepCompletion({
          task,
          activeCanvas: otherCanvas,
          jobs: [],
        }),
      ).some(Boolean),
    ).toBe(false);
  });
});
