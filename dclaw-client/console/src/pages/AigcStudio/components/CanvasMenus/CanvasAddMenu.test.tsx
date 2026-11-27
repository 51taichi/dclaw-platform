import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasAddMenu } from "./CanvasAddMenu";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("CanvasAddMenu", () => {
  it("renders addable node definitions and routes selection", () => {
    const addNode = vi.fn();

    render(<CanvasAddMenu t={t} onAddNode={addNode} />);

    fireEvent.click(screen.getByRole("button", { name: /图片/ }));

    expect(screen.getByText("添加节点")).toBeInTheDocument();
    expect(screen.getByText("文本")).toBeInTheDocument();
    expect(screen.getByText("视频")).toBeInTheDocument();
    expect(screen.getByText("公众号长图")).toBeInTheDocument();
    expect(addNode).toHaveBeenCalledWith("image_generate");
  });

  it("positions itself from the optional anchor", () => {
    render(
      <CanvasAddMenu
        t={t}
        anchor={{ x: 12, y: 34, position: { x: 1, y: 2 } }}
        onAddNode={vi.fn()}
      />,
    );

    expect(screen.getByTestId("aigc-add-node-menu")).toHaveStyle({
      left: "12px",
      top: "34px",
    });
  });
});
