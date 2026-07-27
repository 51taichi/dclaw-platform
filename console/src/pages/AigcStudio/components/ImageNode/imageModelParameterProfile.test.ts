import { describe, expect, it } from "vitest";

import type { AigcCapabilityInfo } from "../../../../api/modules/aigcStudio";
import {
  imageModelParameterProfileFor,
  imageSizeParameterSummary,
  normalizedImageParameterSelection,
} from "./imageModelParameterProfile";

const imageModel = (
  model_id: string,
  model_name: string,
  provider_id = "volcengine",
  provider_name = "Volcano Engine",
): AigcCapabilityInfo => ({
  provider_id,
  provider_name,
  model_id,
  model_name,
  capability: "text_to_image",
  source: "model_registry",
});

describe("imageModelParameterProfile", () => {
  it("uses the Seedream 4.5 recommended resolution and ratio set", () => {
    const profile = imageModelParameterProfileFor(
      imageModel("doubao-seedream-4-5-251128", "doubao-seedream-4-5"),
    );

    expect(profile.kind).toBe("seedream-4-5");
    expect(profile.resolutions).toEqual(["2K", "4K"]);
    expect(profile.aspectRatios).toEqual([
      "1:1",
      "4:3",
      "3:4",
      "16:9",
      "9:16",
      "3:2",
      "2:3",
      "21:9",
      "9:21",
    ]);
    expect(profile.showQuality).toBe(false);
    expect(profile.showPanorama).toBe(false);
    expect(profile.showCamera).toBe(false);
    expect(profile.showAdvanced).toBe(false);
    expect(profile.promptTools).toEqual(["style"]);
    expect(profile.sizeFor("4K", "16:9")).toBe("5504x3040");
    expect(profile.sizeFor("2K", "9:21")).toBe("1344x3136");
  });

  it("uses the Nano2 resolution and ratio set from the MXAPI contract", () => {
    const profile = imageModelParameterProfileFor(
      imageModel("nano2", "Nano Banana2"),
    );

    expect(profile.kind).toBe("nano2");
    expect(profile.resolutions).toEqual(["1K", "2K", "4K"]);
    expect(profile.aspectRatios).toEqual([
      "1:1",
      "3:4",
      "4:3",
      "9:16",
      "16:9",
      "21:9",
    ]);
    expect(profile.defaultResolution).toBe("1K");
    expect(profile.showQuality).toBe(false);
    expect(profile.showPanorama).toBe(false);
    expect(profile.showCamera).toBe(false);
    expect(profile.showAdvanced).toBe(false);
    expect(profile.promptTools).toEqual(["style"]);
  });

  it("uses the MXAPI GPT Image 2 ratio set from the V2 contract", () => {
    const profile = imageModelParameterProfileFor(
      imageModel("gpt-image-2", "GPT Image 2", "mxapi", "MXAPI"),
    );

    expect(profile.kind).toBe("mxapi-gpt-image-2");
    expect(profile.resolutions).toEqual(["1K", "2K", "4K"]);
    expect(profile.aspectRatios).toEqual([
      "1:1",
      "3:2",
      "2:3",
      "4:3",
      "3:4",
      "16:9",
      "9:16",
      "21:9",
      "9:21",
      "3:1",
      "1:3",
    ]);
    expect(profile.aspectRatios).not.toContain("4:5");
    expect(profile.defaultResolution).toBe("1K");
    expect(profile.showQuality).toBe(true);
    expect(profile.showPanorama).toBe(false);
    expect(profile.showCamera).toBe(false);
    expect(profile.showAdvanced).toBe(false);
    expect(profile.promptTools).toEqual(["style"]);
  });

  it("keeps the full parameter surface for unknown image models", () => {
    const profile = imageModelParameterProfileFor(
      imageModel("lib-image", "Lib Image"),
    );

    expect(profile.kind).toBe("full");
    expect(profile.resolutions).toContain("1K");
    expect(profile.aspectRatios).toContain("2:1");
    expect(profile.aspectRatios).toContain("9:21");
    expect(profile.showQuality).toBe(true);
    expect(profile.showPanorama).toBe(true);
    expect(profile.showCamera).toBe(true);
    expect(profile.showAdvanced).toBe(true);
    expect(profile.promptTools).toEqual(["style", "mark", "focus"]);
  });

  it("normalizes stale Seedream 4.5 node values to supported defaults", () => {
    const profile = imageModelParameterProfileFor(
      imageModel("doubao-seedream-4-5-251128", "doubao-seedream-4-5"),
    );

    const selection = normalizedImageParameterSelection(profile, {
      aspectRatio: "2:1",
      imageQuality: "高画质",
      resolution: "1K",
    });

    expect(selection).toEqual({
      aspectRatio: "16:9",
      imageQuality: "",
      resolution: "2K",
    });
    expect(imageSizeParameterSummary(profile, selection)).toBe("16:9 · 2K");
  });
});
