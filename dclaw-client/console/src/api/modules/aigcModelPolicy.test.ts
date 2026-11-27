import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { aigcModelPolicyApi } from "./aigcModelPolicy";

describe("aigcModelPolicyApi", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "admin-token"),
      removeItem: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ categories: {} }),
        text: async () => '{"categories":{}}',
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("saves one ordered AIGC model category", async () => {
    const payload = {
      version: 3,
      models: [{ provider_id: "mxapi", model_id: "gpt-image-2" }],
      default_model: { provider_id: "mxapi", model_id: "gpt-image-2" },
    };

    await aigcModelPolicyApi.saveCategory("image", payload);

    expect(fetch).toHaveBeenCalledWith(
      "/api/admin/aigc-model-policy/image",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    );
  });
});
