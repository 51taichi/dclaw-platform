import { describe, expect, it } from "vitest";

import {
  estimatedImageGenerationMs,
  estimatedImageGenerationSecondsLabel,
  simulatedImageGenerationProgress,
} from "./generationProgress";

describe("generationProgress", () => {
  it("estimates MXAPI GPT Image 2 around the measured local runtime", () => {
    expect(
      estimatedImageGenerationMs({
        providerId: "mxapi",
        modelId: "gpt-image-2",
        parameters: { resolution: "2K", imageCount: 1 },
      }),
    ).toBe(40_000);
  });

  it("uses a shorter Seedream baseline but stretches for higher resolution and multiple images", () => {
    const single2k = estimatedImageGenerationMs({
      providerId: "volcengine-cn",
      modelId: "doubao-seedream-4-5-251128",
      parameters: { resolution: "2K", imageCount: 1 },
    });
    const multi4k = estimatedImageGenerationMs({
      providerId: "volcengine-cn",
      modelId: "doubao-seedream-4-5-251128",
      parameters: { resolution: "4K", imageCount: 3 },
    });

    expect(single2k).toBe(30_000);
    expect(multi4k).toBeGreaterThan(single2k);
  });

  it("formats the same runtime estimate for model menu badges", () => {
    expect(
      estimatedImageGenerationSecondsLabel({
        providerId: "mxapi",
        modelId: "gpt-image-2",
        parameters: { resolution: "2K", imageCount: 1 },
      }),
    ).toBe("40s");
    expect(
      estimatedImageGenerationSecondsLabel({
        providerId: "volcengine-cn",
        modelId: "doubao-seedream-4-5-251128",
        parameters: { resolution: "4K", imageCount: 3 },
      }),
    ).toBe("63s");
  });

  it("simulates progress from 2 to 98 percent without claiming completion", () => {
    expect(simulatedImageGenerationProgress(0, 40_000)).toBe(2);
    expect(simulatedImageGenerationProgress(20_000, 40_000)).toBeGreaterThan(40);
    expect(simulatedImageGenerationProgress(20_000, 40_000)).toBeLessThan(80);
    expect(simulatedImageGenerationProgress(60_000, 40_000)).toBe(98);
  });
});
