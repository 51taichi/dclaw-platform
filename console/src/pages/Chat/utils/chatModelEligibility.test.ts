import { describe, expect, it } from "vitest";

import type { ModelInfo } from "@/api/types";
import { isChatSelectableModel } from "./chatModelEligibility";

const model = (overrides: Partial<ModelInfo> = {}): ModelInfo => ({
  id: "model",
  name: "Model",
  supports_multimodal: false,
  supports_image: false,
  supports_video: false,
  generate_kwargs: {},
  ...overrides,
});

describe("isChatSelectableModel", () => {
  it("accepts LLM models", () => {
    expect(isChatSelectableModel(model({ model_type: "llm" }))).toBe(true);
  });

  it("rejects embedding models", () => {
    expect(isChatSelectableModel(model({ model_type: "embedding" }))).toBe(
      false,
    );
  });

  it("keeps AIGC-only models out of chat selectors", () => {
    expect(
      isChatSelectableModel(model({ aigc_capabilities: ["text_to_image"] })),
    ).toBe(false);
  });
});
