import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { ImageAnnotationEditor } from "./ImageAnnotationEditor";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const wideGeneratedNode: AigcCanvasNode = {
  id: "image-1",
  type: "image_generate",
  position: { x: 0, y: 0 },
  data: {
    title: "图片节点",
    outputs: [
      {
        id: "asset-1",
        kind: "image",
        name: "wide.png",
        path: "/api/user/aigc-studio/assets/asset-1/file",
        width: 2848,
        height: 1600,
      },
    ],
  },
};

describe("ImageAnnotationEditor", () => {
  it("uses the source image ratio for the drawing stage and saved paths", () => {
    const onSave = vi.fn();
    render(
      <ImageAnnotationEditor
        node={wideGeneratedNode}
        sourcePreviewUrl="/api/user/aigc-studio/assets/asset-1/file"
        t={t}
        onCancel={vi.fn()}
        onSave={onSave}
      />,
    );

    expect(screen.getByTestId("aigc-image-annotation-surface")).toHaveStyle({
      aspectRatio: "1000 / 562",
    });
    expect(screen.getByTestId("aigc-image-annotation-stage")).toHaveAttribute(
      "viewBox",
      "0 0 1000 562",
    );

    const stage = screen.getByTestId("aigc-image-annotation-stage");
    fireEvent.pointerDown(stage, { clientX: 10, clientY: 20, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: 110, clientY: 120, pointerId: 1 });
    fireEvent.pointerUp(stage, { clientX: 110, clientY: 120, pointerId: 1 });
    fireEvent.click(screen.getByRole("button", { name: "保存标注" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        annotationViewBox: { width: 1000, height: 562 },
      }),
    );
  });
});
