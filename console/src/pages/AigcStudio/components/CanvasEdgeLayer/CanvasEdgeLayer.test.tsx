import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CanvasEdgeLayer } from "./CanvasEdgeLayer";

describe("CanvasEdgeLayer", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders all edge paths with the shared glow filter", () => {
    render(
      <CanvasEdgeLayer
        edgeLines={[
          { id: "edge-1", path: "M 0 0 C 20 0, 40 20, 60 20" },
          { id: "edge-2", path: "M 10 40 C 30 40, 50 60, 70 60" },
        ]}
      />,
    );

    expect(screen.getByTestId("aigc-edge-layer")).toBeInTheDocument();
    expect(document.querySelector("#aigc-edge-glow")).toBeInTheDocument();
    expect(document.querySelectorAll("g").length).toBe(2);
    expect(document.querySelectorAll("path").length).toBe(10);
    expect(
      document.querySelectorAll("[filter='url(#aigc-edge-glow)']").length,
    ).toBe(4);
  });

  it("shows a scissors action after a long press on an edge and deletes it", () => {
    vi.useFakeTimers();
    const onDeleteEdge = vi.fn();
    render(
      <CanvasEdgeLayer
        edgeLines={[{ id: "edge-1", path: "M 0 0 C 20 0, 40 20, 60 20" }]}
        onDeleteEdge={onDeleteEdge}
      />,
    );

    fireEvent.pointerDown(screen.getByTestId("aigc-edge-hit-edge-1"), {
      clientX: 24,
      clientY: 32,
    });
    act(() => {
      vi.advanceTimersByTime(520);
    });

    const button = screen.getByRole("button", { name: "断开连线" });
    fireEvent.click(button);

    expect(onDeleteEdge).toHaveBeenCalledWith("edge-1");
  });

  it("does not add a hit area to draft drag edges", () => {
    render(
      <CanvasEdgeLayer
        edgeLines={[
          { id: "draft-image-1-right", path: "M 0 0 C 20 0, 40 20, 60 20" },
        ]}
        onDeleteEdge={vi.fn()}
      />,
    );

    expect(
      screen.queryByTestId("aigc-edge-hit-draft-image-1-right"),
    ).not.toBeInTheDocument();
  });
});
