import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AigcCanvas, AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { LongImageExportNode } from "./LongImageExportNode";

const t = ((
  _key: string,
  fallback?: string,
  values?: Record<string, unknown>,
) => {
  const template = fallback ?? _key;
  return Object.entries(values ?? {}).reduce(
    (result, [key, value]) => result.replace(`{{${key}}}`, String(value)),
    template,
  );
}) as never;

const longImageNode: AigcCanvasNode = {
  id: "long-1",
  type: "long_image_export",
  position: { x: 0, y: 0 },
  data: {
    title: "公众号长图",
    outputs: [
      {
        id: "full-asset",
        kind: "image",
        name: "long-full.png",
        path: "blob:long-full-preview",
        mime_type: "image/png",
        created_at: "2026-07-03T00:00:00Z",
      },
      {
        id: "slice-asset-1",
        kind: "image",
        name: "slice-01.png",
        url: "/api/user/aigc-studio/assets/slice-asset-1/file",
        mime_type: "image/png",
        created_at: "2026-07-03T00:00:00Z",
      },
    ],
  },
};

const canvas: AigcCanvas = {
  id: "canvas-1",
  name: "小说推文长图",
  nodes: [
    {
      id: "text-1",
      type: "prompt",
      position: { x: 0, y: 0 },
      data: {
        title: "第一章",
        text: "她推开门，看见满城灯火。",
      },
    },
    longImageNode,
  ],
  edges: [{ id: "edge-text-long", source: "text-1", target: "long-1" }],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-07-03T00:00:00Z",
  updated_at: "2026-07-03T00:00:00Z",
};

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

const restoreUrlObjectMethods = () => {
  if (originalCreateObjectUrl) {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: originalCreateObjectUrl,
    });
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectUrl) {
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectUrl,
    });
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
  }
};

describe("LongImageExportNode", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document
      .querySelectorAll("[data-aigc-download-link]")
      .forEach((element) => element.remove());
    restoreUrlObjectMethods();
  });

  it("downloads generated slices with the authenticated asset behavior", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi.fn().mockResolvedValue(new Blob(["slice"], { type: "image/png" })),
    });
    const createObjectUrl = vi.fn(() => "blob:downloaded-slice");
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });

    render(
      <LongImageExportNode
        node={longImageNode}
        canvas={canvas}
        selected
        exporting={false}
        t={t}
        onExport={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "下载完整长图" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下载切片 1" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:3000/api/user/aigc-studio/assets/slice-asset-1/file",
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(document.querySelector("a[download='slice-01.png']")).toHaveAttribute(
      "href",
      "blob:downloaded-slice",
    );
  });
});
