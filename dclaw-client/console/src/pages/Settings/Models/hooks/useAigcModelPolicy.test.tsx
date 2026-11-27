import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { aigcModelPolicyApi } from "@/api/modules/aigcModelPolicy";
import { useAigcModelPolicy } from "./useAigcModelPolicy";

vi.mock("@/api/modules/aigcModelPolicy", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/api/modules/aigcModelPolicy")>();
  return {
    ...original,
    aigcModelPolicyApi: {
      getInventory: vi.fn(),
      getPolicies: vi.fn(),
      saveCategory: vi.fn(),
    },
  };
});

const emptyCategories = {
  text: null,
  image: null,
  video: null,
  audio: null,
};

describe("useAigcModelPolicy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(aigcModelPolicyApi.getInventory).mockResolvedValue({
      categories: { text: [], image: [], video: [], audio: [] },
      uncategorized: [],
    });
    vi.mocked(aigcModelPolicyApi.getPolicies).mockResolvedValue({
      categories: emptyCategories,
    });
    vi.mocked(aigcModelPolicyApi.saveCategory).mockReset();
  });

  it("keeps edits isolated to one category", async () => {
    const { result } = renderHook(() => useAigcModelPolicy());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.addModel("image", {
        provider_id: "mxapi",
        model_id: "gpt-image-2",
      });
    });

    expect(result.current.drafts.image.models).toHaveLength(1);
    expect(result.current.drafts.video.models).toHaveLength(0);
    expect(result.current.dirtyCategories).toEqual(new Set(["image"]));
  });

  it("keeps a conflicting draft dirty and refreshes server state", async () => {
    vi.mocked(aigcModelPolicyApi.saveCategory).mockRejectedValue(
      Object.assign(new Error("conflict"), { status: 409 }),
    );
    const { result } = renderHook(() => useAigcModelPolicy());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => {
      result.current.addModel("image", {
        provider_id: "mxapi",
        model_id: "gpt-image-2",
      });
    });

    await act(async () => {
      await expect(result.current.saveCategory("image")).rejects.toThrow(
        "conflict",
      );
    });

    expect(result.current.dirtyCategories.has("image")).toBe(true);
    expect(aigcModelPolicyApi.getPolicies).toHaveBeenCalledTimes(2);
  });
});
