import { describe, expect, it } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { directorStageProjectFromNode } from "./directorStageTypes";

describe("directorStageProjectFromNode", () => {
  it("loads legacy projects without a lighting preset", () => {
    const node = {
      id: "director-stage-1",
      type: "director_stage",
      position: { x: 0, y: 0 },
      data: {
        directorStageProject: {
          version: 1,
          scene: {
            backgroundColor: "#101114",
            sourceImageUrl: "https://example.com/reference.png",
          },
          objects: [],
          cameras: [],
        },
      },
    } as AigcCanvasNode;

    expect(directorStageProjectFromNode(node)?.scene).toEqual({
      backgroundColor: "#101114",
      lightingPreset: "studio",
      sourceImageUrl: "https://example.com/reference.png",
    });
  });

  it("restores valid uploaded model asset references", () => {
    const node = {
      id: "director-stage-1",
      type: "director_stage",
      position: { x: 0, y: 0 },
      data: {
        directorStageProject: {
          version: 1,
          modelAssets: [
            {
              id: "uploaded-model-asset-1",
              assetId: "asset-1",
              kind: "character",
              name: "Hero",
              fileName: "hero.glb",
              url: "/api/user/aigc-studio/assets/asset-1/file",
              mimeType: "model/gltf-binary",
              size: 4096,
              createdAt: 1783900800000,
            },
          ],
          objects: [],
          cameras: [],
        },
      },
    } as AigcCanvasNode;

    expect(directorStageProjectFromNode(node)?.modelAssets).toEqual([
      expect.objectContaining({
        id: "uploaded-model-asset-1",
        assetId: "asset-1",
        kind: "character",
        fileName: "hero.glb",
      }),
    ]);
  });
});
