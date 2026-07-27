import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasEmptyProjectLauncher } from "./CanvasEmptyProjectLauncher";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("CanvasEmptyProjectLauncher", () => {
  it("renders the empty project prompt and routes project creation", () => {
    const createCanvas = vi.fn();

    render(<CanvasEmptyProjectLauncher t={t} onCreateCanvas={createCanvas} />);

    fireEvent.click(screen.getByRole("button", { name: /新建项目/ }));

    expect(screen.getByText("暂无项目")).toBeInTheDocument();
    expect(createCanvas).toHaveBeenCalledTimes(1);
  });
});
