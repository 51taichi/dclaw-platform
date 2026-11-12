import { describe, expect, it } from "vitest";

import { resolveWorkflowOutputAssetId } from "./workflowOutput";

describe("resolveWorkflowOutputAssetId", () => {
  it("walks upstream through an output wrapper to the generated asset", () => {
    expect(
      resolveWorkflowOutputAssetId(
        [
          {
            id: "video-1",
            type: "video_generate",
            position: { x: 0, y: 0 },
            data: { outputs: [{ id: "asset-video-1", kind: "video" }] },
          },
          {
            id: "output-1",
            type: "output",
            position: { x: 1, y: 0 },
            data: {},
          },
        ],
        [{ id: "edge-1", source: "video-1", target: "output-1" }],
        "output-1",
      ),
    ).toBe("asset-video-1");
  });

  it("fails closed for cycles or missing output assets", () => {
    expect(
      resolveWorkflowOutputAssetId(
        [
          { id: "a", type: "output", position: { x: 0, y: 0 }, data: {} },
          { id: "b", type: "output", position: { x: 1, y: 0 }, data: {} },
        ],
        [
          { id: "ab", source: "a", target: "b" },
          { id: "ba", source: "b", target: "a" },
        ],
        "a",
      ),
    ).toBe("");
  });
});
