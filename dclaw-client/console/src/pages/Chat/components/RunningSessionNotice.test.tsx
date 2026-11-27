import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RunningSessionNotice from "./RunningSessionNotice";

describe("RunningSessionNotice", () => {
  it("shows a friendly generating status when visible", () => {
    render(<RunningSessionNotice visible />);

    expect(screen.getByText("DClaw 正在继续生成")).toBeInTheDocument();
    expect(
      screen.getByText("切换回来后会自动同步结果，你可以放心去看别的任务。"),
    ).toBeInTheDocument();
  });

  it("renders nothing when hidden", () => {
    const { container } = render(<RunningSessionNotice visible={false} />);

    expect(container).toBeEmptyDOMElement();
  });
});
