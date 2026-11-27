import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { ImageCaptureGroupNode } from "./ImageCaptureGroupNode";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("ImageCaptureGroupNode", () => {
  it("selects a capture frame for downstream workflows", () => {
    const node: AigcCanvasNode = {
      id: "capture-group-1",
      type: "reference_asset",
      position: { x: 400, y: 120 },
      data: {
        title: "导演台截图组",
        previewKind: "image_capture_group",
        captureCount: 2,
        selectedCaptureId: "capture-1",
        captureFrames: [
          {
            id: "capture-1",
            label: "机位01",
            assetPreviewUrl: "/capture-1.png",
          },
          {
            id: "capture-2",
            label: "机位02",
            assetPreviewUrl: "/capture-2.png",
          },
        ],
      },
    };
    const handleImageCaptureGroupSelect = vi.fn();

    render(
      <ImageCaptureGroupNode
        node={node}
        t={t}
        workflow={
          {
            handleImageCaptureGroupSelect,
            handleImageCaptureGroupSendToImage: vi.fn(),
          } as never
        }
      />,
    );

    expect(screen.getByRole("button", { name: "选择机位01" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "选择机位02" }));

    expect(handleImageCaptureGroupSelect).toHaveBeenCalledWith(
      node,
      "capture-2",
    );
  });
});
