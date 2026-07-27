import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildAuthHeaders } from "../../../api/authHeaders";
import {
  AuthenticatedAssetImage,
  AuthenticatedAssetVideo,
  clearAuthenticatedAssetImageCache,
  shouldFetchAuthenticatedAsset,
  useAuthenticatedAssetSource,
} from "./AuthenticatedAssetImage";

vi.mock("../../../api/authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

describe("AuthenticatedAssetImage", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.restoreAllMocks();
    clearAuthenticatedAssetImageCache();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            url: "https://static.example.test/aigc/generated/asset-1.jpg?signature=1",
            expires_in: 900,
          }),
          { headers: { "content-type": "application/json" } },
        ),
      ),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:loaded-image");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.mocked(buildAuthHeaders).mockReturnValue({
      Authorization: "Bearer test-token",
    });
  });

  it("resolves protected API image assets to direct signed URLs before rendering", async () => {
    render(
      <AuthenticatedAssetImage
        src="http://127.0.0.1:18088/api/user/aigc-studio/assets/asset-1/file"
        alt="generated"
      />,
    );

    expect(screen.getByAltText("generated")).toHaveAttribute(
      "data-authenticated-asset-state",
      "loading",
    );

    await waitFor(() =>
      expect(screen.getByAltText("generated")).toHaveAttribute(
        "src",
        "https://static.example.test/aigc/generated/asset-1.jpg?signature=1",
      ),
    );

    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:18088/api/user/aigc-studio/assets/asset-1/signed-url",
      {
        credentials: "include",
        headers: { Authorization: "Bearer test-token" },
      },
    );
  });

  it("resolves protected API video assets to direct signed URLs before rendering", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          url: "https://static.example.test/aigc/generated/video-1.mp4?signature=1",
          expires_in: 900,
        }),
        { headers: { "content-type": "application/json" } },
      ),
    );

    render(
      <AuthenticatedAssetVideo
        src="http://127.0.0.1:18088/api/user/aigc-studio/assets/video-1/file"
        aria-label="generated video"
      />,
    );

    expect(screen.getByLabelText("generated video")).toHaveAttribute(
      "data-authenticated-asset-state",
      "loading",
    );

    await waitFor(() =>
      expect(screen.getByLabelText("generated video")).toHaveAttribute(
        "src",
        "https://static.example.test/aigc/generated/video-1.mp4?signature=1",
      ),
    );

    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:18088/api/user/aigc-studio/assets/video-1/signed-url",
      {
        credentials: "include",
        headers: { Authorization: "Bearer test-token" },
      },
    );
  });

  it("reuses signed URLs when protected API image assets remount", async () => {
    const first = render(
      <AuthenticatedAssetImage
        src="http://127.0.0.1:18088/api/user/aigc-studio/assets/asset-1/file"
        alt="first"
      />,
    );

    await waitFor(() =>
      expect(screen.getByAltText("first")).toHaveAttribute(
        "src",
        "https://static.example.test/aigc/generated/asset-1.jpg?signature=1",
      ),
    );
    first.unmount();

    render(
      <AuthenticatedAssetImage
        src="http://127.0.0.1:18088/api/user/aigc-studio/assets/asset-1/file"
        alt="second"
      />,
    );

    await waitFor(() =>
      expect(screen.getByAltText("second")).toHaveAttribute(
        "src",
        "https://static.example.test/aigc/generated/asset-1.jpg?signature=1",
      ),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("can proxy protected binary assets instead of returning a signed URL", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(new Blob(["glb-data"], { type: "model/gltf-binary" })),
    );

    const { result } = renderHook(() =>
      useAuthenticatedAssetSource(
        "http://127.0.0.1:18088/api/user/aigc-studio/assets/model-1/file",
        { preferProxy: true },
      ),
    );

    await waitFor(() => expect(result.current.loadState).toBe("loaded"));

    expect(result.current.resolvedSrc).toBe("blob:loaded-image");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:18088/api/user/aigc-studio/assets/model-1/file",
      {
        credentials: "include",
        headers: { Authorization: "Bearer test-token" },
      },
    );
  });

  it("normalizes same-host http API assets to the current https origin", async () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("https://dclaw.deepmega.cn/aigc-studio"),
    });

    render(
      <AuthenticatedAssetImage
        src="http://dclaw.deepmega.cn/api/user/aigc-studio/assets/asset-1/file"
        alt="uploaded"
      />,
    );

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "https://dclaw.deepmega.cn/api/user/aigc-studio/assets/asset-1/signed-url",
        {
          credentials: "include",
          headers: { Authorization: "Bearer test-token" },
        },
      ),
    );
  });

  it("leaves public image URLs as direct img sources", () => {
    render(
      <AuthenticatedAssetImage src="https://example.com/result.jpg" alt="public" />,
    );

    expect(screen.getByAltText("public")).toHaveAttribute(
      "src",
      "https://example.com/result.jpg",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("detects API user and admin assets as protected sources", () => {
    expect(shouldFetchAuthenticatedAsset("/api/user/aigc-studio/assets/a/file")).toBe(
      true,
    );
    expect(shouldFetchAuthenticatedAsset("https://host/api/admin/files/a")).toBe(
      true,
    );
    expect(shouldFetchAuthenticatedAsset("blob:preview")).toBe(false);
    expect(shouldFetchAuthenticatedAsset("https://example.com/image.jpg")).toBe(
      false,
    );
  });
});
