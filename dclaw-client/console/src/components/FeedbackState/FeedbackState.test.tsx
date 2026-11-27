import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FeedbackState from ".";

describe("FeedbackState", () => {
  it("uses a polite busy status for loading feedback", () => {
    render(<FeedbackState variant="loading" title="正在加载" />);

    const state = screen.getByRole("status");
    expect(state).toHaveAttribute("data-feedback-state", "loading");
    expect(state).toHaveAttribute("aria-busy", "true");
    expect(state.querySelector("img")).toHaveAttribute("src");
  });

  it("uses an alert for an error and renders its recovery action", () => {
    render(
      <FeedbackState
        variant="error"
        title="暂时无法打开"
        action={<button>重试</button>}
      />,
    );

    expect(screen.getByRole("alert")).toHaveAttribute(
      "data-feedback-state",
      "error",
    );
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("can fill its parent region for vertical centering", () => {
    render(<FeedbackState variant="loading" title="正在加载" fill />);

    expect(screen.getByRole("status").className).toContain("fill");
  });
});
