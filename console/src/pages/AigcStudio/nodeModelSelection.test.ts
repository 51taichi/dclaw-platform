import { describe, expect, it } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../api/modules/aigcStudio";
import {
  categoryForCapability,
  modelForNewNode,
  modelForNode,
  modelSelectionState,
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
  it("maps text, image, video, and audio capabilities to policy categories", () => {
    expect(categoryForCapability("storyboard")).toBe("text");
    expect(categoryForCapability("text_to_image")).toBe("image");
    expect(categoryForCapability("image_to_video")).toBe("video");
    expect(categoryForCapability("text_to_audio")).toBe("audio");
  });

  it("uses the server effective default instead of the first capability", () => {
    const first = imageModel("text_to_image", "first");
    const preferred = imageModel("text_to_image", "preferred");

    expect(
      modelForNewNode([first, preferred], {
        provider_id: "volcengine",
        model_id: "preferred",
      }),
    ).toEqual(preferred);
  });

  it("shows the configured fallback while preserving migration state", () => {
    const fallback = imageModel("text_to_image", "fallback");
    const node: AigcCanvasNode = {
      id: "image-1",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        providerId: "mxapi",
        providerName: "MXAPI",
        modelId: "removed-model",
        modelLabel: "Removed model",
        modelCapability: "text_to_image",
      },
    };

    const state = modelSelectionState([fallback], node, "text_to_image", {
      provider_id: "volcengine",
      model_id: "fallback",
    });
    expect(state.invalidSavedModel).toBe(true);
    expect(state.selected?.model_id).toBe("fallback");
    expect(state.fallback).toEqual(fallback);
    expect(node.data.modelId).toBe("removed-model");
    expect(modelOptionsForNode([fallback], node, "text_to_image")).toEqual([
      fallback,
    ]);
  });

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

  it("excludes a stale node snapshot from configured options", () => {
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

  it("blocks a stale snapshot when no configured model is available", () => {
    const node: AigcCanvasNode = {
      id: "image-1",
      type: "image_generate",
      position: { x: 0, y: 0 },
      data: {
        providerId: "volcengine",
        modelId: "removed-model",
        modelLabel: "Removed model",
      },
    };

    const state = modelSelectionState([], node, "text_to_image");

    expect(state.invalidSavedModel).toBe(true);
    expect(state.fallback).toBeNull();
    expect(state.selected?.model_id).toBe("removed-model");
  });

  it("offers every compatible configured model for a workflow-bound node", () => {
    const bound = model("image_to_video", "seedance2", "Seedance 2.0");
    const alternative = model(
      "image_to_video",
      "grok-imagine-video-1.5",
      "Grok Imagine Video 1.5",
    );
    const wrongOperation = model(
      "text_to_video",
      "text-only-video-model",
      "Text Only Video Model",
    );
    const node: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 0, y: 0 },
      data: {
        workflowLogicalNodeId: "clip",
        providerId: "volcengine",
        modelId: "seedance2",
        modelCapability: "image_to_video",
      },
    };

    expect(
      modelOptionsForNode(
        [bound, alternative, wrongOperation],
        node,
        "image_to_video",
      ),
    ).toEqual([bound, alternative]);
    expect(modelForNode([bound, alternative], node, "image_to_video")).toEqual(
      bound,
    );
  });

  it("falls back to the configured default when a workflow model was removed", () => {
    const configured = model(
      "image_to_video",
      "grok-imagine-video-1.5",
      "Grok Imagine Video 1.5",
    );
    const node: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 0, y: 0 },
      data: {
        workflowLogicalNodeId: "clip",
        providerId: "mxapi",
        modelId: "removed-video-model",
        modelCapability: "image_to_video",
      },
    };

    expect(
      modelForNode([configured], node, "image_to_video", {
        provider_id: configured.provider_id,
        model_id: configured.model_id,
      }),
    ).toEqual(configured);
    expect(modelOptionsForNode([configured], node, "image_to_video")).toEqual([
      configured,
    ]);
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
