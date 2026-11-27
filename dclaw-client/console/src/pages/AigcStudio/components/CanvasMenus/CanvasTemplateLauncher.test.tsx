import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasTemplateLauncher } from "./CanvasTemplateLauncher";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("CanvasTemplateLauncher", () => {
  it("renders template cards and routes template selection", () => {
    const template = vi.fn();

    render(<CanvasTemplateLauncher t={t} onTemplate={template} />);

    fireEvent.click(screen.getByTestId("aigc-template-character"));

    expect(screen.getByText("双击画布 自由生成节点")).toBeInTheDocument();
    expect(screen.getByText("故事脚本生成")).toBeInTheDocument();
    expect(screen.getByText("首帧图生视频")).toBeInTheDocument();
    expect(template).toHaveBeenCalledWith("character");
  });
});
