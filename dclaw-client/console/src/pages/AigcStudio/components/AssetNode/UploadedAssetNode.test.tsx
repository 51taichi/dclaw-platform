import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { UploadedAssetNode } from "./UploadedAssetNode";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const uploadedNode: AigcCanvasNode = {
  id: "asset-1",
  type: "reference_asset",
  position: { x: 160, y: 120 },
  data: {
    title: "图片节点",
    assetName: "reference.png",
    assetPreviewUrl: "blob:reference",
    previewKind: "uploaded_source",
  },
};

describe("UploadedAssetNode", () => {
  it("renders uploaded asset preview and forwards replacement files", () => {
    const onReplace = vi.fn();
    const replacement = new File(["next"], "next.png", { type: "image/png" });

    render(
      <UploadedAssetNode node={uploadedNode} t={t} onReplace={onReplace} />,
    );

    expect(screen.getByText("图片节点")).toBeInTheDocument();
    expect(screen.getByAltText("reference.png")).toHaveAttribute(
      "src",
      "blob:reference",
    );

    fireEvent.change(screen.getByLabelText("替换参考图"), {
      target: { files: [replacement] },
    });

    expect(onReplace).toHaveBeenCalledWith(uploadedNode, replacement);
  });

  it("sizes uploaded image cards from stored image dimensions", () => {
    render(
      <UploadedAssetNode
        node={{
          ...uploadedNode,
          data: {
            ...uploadedNode.data,
            assetWidth: 1080,
            assetHeight: 1080,
          },
        }}
        t={t}
        onReplace={vi.fn()}
      />,
    );

    expect(screen.getByTestId("aigc-uploaded-asset-card")).toHaveStyle({
      aspectRatio: "1080 / 1080",
    });
  });

  it("persists uploaded image dimensions after the preview loads", () => {
    const onUpdateNodeData = vi.fn();
    render(
      <UploadedAssetNode
        node={uploadedNode}
        t={t}
        onReplace={vi.fn()}
        onUpdateNodeData={onUpdateNodeData}
      />,
    );

    const image = screen.getByAltText("reference.png");
    Object.defineProperty(image, "naturalWidth", {
      configurable: true,
      value: 960,
    });
    Object.defineProperty(image, "naturalHeight", {
      configurable: true,
      value: 640,
    });
    fireEvent.load(image);

    expect(onUpdateNodeData).toHaveBeenCalledWith("asset-1", {
      assetWidth: 960,
      assetHeight: 640,
    });
  });

  it("uses authenticated image loading for protected API previews", () => {
    render(
      <UploadedAssetNode
        node={{
          ...uploadedNode,
          data: {
            ...uploadedNode.data,
            assetPreviewUrl: "/api/user/aigc-studio/assets/reference.png/file",
          },
        }}
        t={t}
        onReplace={vi.fn()}
      />,
    );

    expect(screen.getByAltText("reference.png")).toHaveAttribute(
      "data-authenticated-asset",
      "true",
    );
  });

  it("shows a fallback when the asset has no preview url", () => {
    render(
      <UploadedAssetNode
        node={{
          ...uploadedNode,
          data: {
            ...uploadedNode.data,
            assetPreviewUrl: "",
          },
        }}
        t={t}
        onReplace={vi.fn()}
      />,
    );

    expect(screen.getByText("reference.png")).toBeInTheDocument();
  });

  it("keeps image annotation previews aligned to the source image ratio", () => {
    render(
      <UploadedAssetNode
        node={{
          ...uploadedNode,
          data: {
            ...uploadedNode.data,
            title: "标注",
            assetRole: "image_annotation",
            isAnnotation: true,
            sourceImageWidth: 2848,
            sourceImageHeight: 1600,
            annotationViewBoxWidth: 1000,
            annotationViewBoxHeight: 562,
            annotationPaths: [
              {
                id: "path-1",
                points: [
                  { x: 430, y: 90 },
                  { x: 600, y: 180 },
                ],
              },
            ],
          },
        }}
        t={t}
        onReplace={vi.fn()}
      />,
    );

    expect(screen.getByTestId("aigc-uploaded-asset-card")).toHaveStyle({
      aspectRatio: "2848 / 1600",
    });
    expect(
      screen.getByTestId("aigc-uploaded-asset-annotation"),
    ).toHaveAttribute("viewBox", "0 0 1000 562");
    expect(screen.queryByLabelText("替换参考图")).not.toBeInTheDocument();
  });
});
