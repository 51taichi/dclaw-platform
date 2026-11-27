import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasContextMenu } from "./CanvasContextMenu";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;
const menu = { x: 20, y: 30, position: { x: 200, y: 300 } };

describe("CanvasContextMenu", () => {
  it("keeps add-node choices collapsed until the section is opened", () => {
    const addNodeAt = vi.fn();

    render(
      <CanvasContextMenu
        menu={menu}
        clipboardNode={null}
        t={t}
        onAddNodeAt={addNodeAt}
        onUploadImage={vi.fn()}
        onUploadVideo={vi.fn()}
        onUploadAudio={vi.fn()}
        onPasteNode={vi.fn()}
      />,
    );

    const menuElement = screen.getByTestId("aigc-canvas-context-menu");
    expect(
      within(menuElement).getByRole("button", { name: "添加节点" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      within(menuElement).queryByRole("button", { name: "图片" }),
    ).not.toBeInTheDocument();

    fireEvent.click(within(menuElement).getByRole("button", { name: "添加节点" }));
    expect(
      within(menuElement).getByRole("button", { name: "添加节点" }),
    ).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "图片" }));

    expect(addNodeAt).toHaveBeenCalledWith("image_generate", menu.position);
    expect(screen.getByTestId("aigc-canvas-context-menu")).toHaveStyle({
      left: "20px",
      top: "30px",
    });
  });

  it("routes upload and paste actions", () => {
    const uploadImage = vi.fn();
    const uploadVideo = vi.fn();
    const uploadAudio = vi.fn();
    const pasteNode = vi.fn();

    render(
      <CanvasContextMenu
        menu={menu}
        clipboardNode={{ id: "copied-node" }}
        t={t}
        onAddNodeAt={vi.fn()}
        onUploadImage={uploadImage}
        onUploadVideo={uploadVideo}
        onUploadAudio={uploadAudio}
        onPasteNode={pasteNode}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /上传图片/ }));
    fireEvent.click(screen.getByRole("button", { name: /上传视频/ }));
    fireEvent.click(screen.getByRole("button", { name: /上传音频/ }));
    fireEvent.click(screen.getByRole("button", { name: /粘贴/ }));

    expect(uploadImage).toHaveBeenCalledTimes(1);
    expect(uploadVideo).toHaveBeenCalledTimes(1);
    expect(uploadAudio).toHaveBeenCalledTimes(1);
    expect(pasteNode).toHaveBeenCalledTimes(1);
  });
});
