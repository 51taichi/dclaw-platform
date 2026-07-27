import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasQuickTemplateMenu } from "./CanvasQuickTemplateMenu";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;
const menu = { x: 44, y: 55, position: { x: 400, y: 500 } };

describe("CanvasQuickTemplateMenu", () => {
  it("renders quick templates and routes selection with the canvas position", () => {
    const template = vi.fn();

    render(<CanvasQuickTemplateMenu menu={menu} t={t} onTemplate={template} />);

    fireEvent.click(screen.getByTestId("aigc-quick-template-story"));

    expect(screen.getByText("双击画布 自由生成节点")).toBeInTheDocument();
    expect(screen.getByText("角色三视图")).toBeInTheDocument();
    expect(template).toHaveBeenCalledWith("story", menu.position);
    expect(screen.getByTestId("aigc-quick-template-menu")).toHaveStyle({
      left: "44px",
      top: "55px",
    });
  });
});
