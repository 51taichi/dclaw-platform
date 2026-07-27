import { describe, expect, it } from "vitest";

import {
  addDirectorStageAsset,
  addUploadedDirectorStageModel,
  applyDirectorStageScenePreset,
  DIRECTOR_STAGE_PROP_BOX_ID,
} from "./directorStageCatalog";
import { createDefaultDirectorStageProject } from "./directorStageTypes";

describe("directorStageCatalog", () => {
  it("creates stable object ids after an earlier asset was deleted", () => {
    const initial = createDefaultDirectorStageProject();
    const first = addDirectorStageAsset(initial, DIRECTOR_STAGE_PROP_BOX_ID);
    const withSecond = addDirectorStageAsset(first, DIRECTOR_STAGE_PROP_BOX_ID);
    const afterDelete = {
      ...withSecond,
      objects: withSecond.objects.filter((item) => item.id !== "prop-1"),
    };

    const result = addDirectorStageAsset(
      afterDelete,
      DIRECTOR_STAGE_PROP_BOX_ID,
    );

    expect(result.objects.map((item) => item.id)).toEqual(["prop-2", "prop-1"]);
  });

  it("preserves the upstream reference image when applying a scene template", () => {
    const project = createDefaultDirectorStageProject(
      "https://example.com/reference.png",
    );

    const result = applyDirectorStageScenePreset(project, "dialogue");

    expect(result.scene).toEqual(
      expect.objectContaining({
        sourceImageUrl: "https://example.com/reference.png",
        lightingPreset: "soft",
      }),
    );
    expect(result.objects).toHaveLength(2);
    expect(result.cameras).toHaveLength(3);
  });

  it("registers and reuses an uploaded model without duplicating its asset record", () => {
    const model = {
      id: "uploaded-model-asset-1",
      assetId: "asset-1",
      kind: "prop" as const,
      name: "沙发",
      fileName: "sofa.glb",
      url: "/api/user/aigc-studio/assets/asset-1/file",
      createdAt: 1783900800000,
    };

    const first = addUploadedDirectorStageModel(
      createDefaultDirectorStageProject(),
      model,
    );
    const second = addUploadedDirectorStageModel(first, model);

    expect(second.modelAssets).toEqual([model]);
    expect(second.objects).toHaveLength(2);
    expect(second.objects.map((item) => item.modelId)).toEqual([
      model.id,
      model.id,
    ]);
  });
});
