import { describe, expect, it } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../api/modules/aigcStudio";
import {
  modelForNode,
  modelOptionsForCapability,
  modelOptionsForNode,
} from "./nodeModelSelection";

const imageModel = (
  capability: string,
  model_id = "doubao-seedream-5-0-260128",
): AigcCapabilityInfo => ({
  provider_id: "volcengine",
  provider_name: "Volcano Engine",
  model_id,
  model_name: model_id,
  capability,
  source: "model_registry",
});

describe("nodeModelSelection", () => {
  it("deduplicates multi-capability image models for component model pickers", () => {
    expect(
      modelOptionsForCapability(
        [
          imageModel("image_edit"),
          imageModel("text_to_image"),
          imageModel("image_to_image"),
          imageModel("text_to_image", "doubao-seedream-4-5-251128"),
        ],
        "text_to_image",
      ),
    ).toEqual([
      imageModel("text_to_image"),
      imageModel("text_to_image", "doubao-seedream-4-5-251128"),
    ]);
  });

  it("does not expose a stale node snapshot when configured options exist", () => {
    const configuredModel = model("storyboard", "glm-4-7", "GLM-4.7");
    const node: AigcCanvasNode = {
      id: "text-1",
      type: "prompt",
      position: { x: 0, y: 0 },
      data: {
        providerId: "modelscope",
        providerName: "ModelScope",
        modelId: "Qwen/Qwen3.5-122B-A10B",
        modelLabel: "Qwen3.5-122B-A10B",
        modelCapability: "storyboard",
      },
    };

    expect(modelOptionsForNode([configuredModel], node, "storyboard")).toEqual([
      configuredModel,
    ]);
    expect(modelForNode([configuredModel], node, "storyboard")).toEqual(
      configuredModel,
    );
  });
});

const model = (
  capability: string,
  model_id: string,
  model_name = model_id,
): AigcCapabilityInfo => ({
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id,
  model_name,
  capability,
  source: "model_registry",
});

describe("video model selection", () => {
  it("keeps reference-only video understanding models out of generation pickers", () => {
    expect(
      modelOptionsForCapability(
        [
          model("reference_video", "qwen3.5-122b-a10b", "Qwen3.5-122B-A10B"),
          model("text_to_video", "seedance2", "Seedance 2.0"),
          model("image_to_video", "seedance2-fast", "Seedance 2.0 Fast"),
          model("reference_video", "kimi-k2.5", "Kimi K2.5"),
        ],
        "text_to_video",
      ).map((item) => item.model_id),
    ).toEqual(["seedance2", "seedance2-fast"]);
  });
});
