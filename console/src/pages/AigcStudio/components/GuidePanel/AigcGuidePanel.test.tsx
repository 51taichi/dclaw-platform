import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AigcGuidePanel } from "./AigcGuidePanel";

const task = {
  binding: {
    installation_id: "installation-1",
    conversation_id: "conversation-1",
    material_task_id: "task-1",
    canvas_id: "canvas-1",
    node_id: "node-1",
  },
  status: "IN_PROGRESS",
};

const operation = {
  operation_id: "aigc.text_to_video.create",
  version: "1" as const,
  title: "从文字提示词创建视频素材",
  human_guide: [
    {
      step_id: "open-studio",
      title: "确认进入工作室",
      instruction: "确认工作室已打开。",
      control_id: "nav.aigc-studio",
      action: "click" as const,
      success_signal: "画布出现",
      recovery: "返回任务卡片重新进入",
    },
    {
      step_id: "create-project",
      title: "创建项目",
      instruction: "点击新建项目。",
      control_id: "aigc.canvas.create",
      action: "click" as const,
      success_signal: "项目出现",
      recovery: "刷新后重试",
    },
  ],
};

describe("AigcGuidePanel", () => {
  beforeEach(() => {
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("resolves the exact platform control and persists the next step", async () => {
    const user = userEvent.setup();
    const control = document.createElement("button");
    control.dataset.platformControlId = "nav.aigc-studio";
    document.body.append(control);
    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
      />,
    );
    await user.click(screen.getByRole("button", { name: "定位当前控件" }));
    expect(control.dataset.platformGuideHighlight).toBe("true");
    await user.click(screen.getByRole("button", { name: "本步已完成" }));
    expect(screen.getByText("创建项目")).toBeInTheDocument();
    expect(localStorage.getItem("dclaw:aigc-guide:task-1:step")).toBe("1");
    control.remove();
  });

  it("fails closed when the exact control is missing", () => {
    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
      />,
    );
    expect(screen.getByText(/控件不可用/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本步已完成" })).toBeDisabled();
  });

  it("does not advance an unrelated canvas", () => {
    const control = document.createElement("button");
    control.dataset.platformControlId = "nav.aigc-studio";
    document.body.append(control);
    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-other"
      />,
    );
    expect(screen.getByText(/不属于此任务/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本步已完成" })).toBeDisabled();
    control.remove();
  });

  it("restores the exact persisted guide step after leaving the studio", async () => {
    localStorage.setItem("dclaw:aigc-guide:task-1:step", "1");
    const control = document.createElement("button");
    control.dataset.platformControlId = "aigc.canvas.create";
    document.body.append(control);

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("创建项目")).toBeInTheDocument(),
    );
    expect(screen.queryByText("确认进入工作室")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "提交给专家审核" }),
    ).toBeEnabled();
    control.remove();
  });

  it("shows the in-page expert review and prevents duplicate submits while pending", async () => {
    localStorage.setItem("dclaw:aigc-guide:task-1:step", "1");
    const control = document.createElement("button");
    control.dataset.platformControlId = "aigc.canvas.create";
    document.body.append(control);
    let resolveReview!: (value: string) => void;
    const onSubmit = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolveReview = resolve;
        }),
    );
    const user = userEvent.setup();

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        onSubmit={onSubmit}
      />,
    );

    const submit = screen.getByRole("button", { name: "提交给专家审核" });
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "专家审核中…" })).toBeDisabled();
    resolveReview("审核通过，可以返回会话继续。");
    expect(
      await screen.findByText("审核通过，可以返回会话继续。"),
    ).toBeInTheDocument();
    control.remove();
  });

  it("keeps progress and offers a safe retry message when review fails", async () => {
    localStorage.setItem("dclaw:aigc-guide:task-1:step", "1");
    const control = document.createElement("button");
    control.dataset.platformControlId = "aigc.canvas.create";
    document.body.append(control);
    const user = userEvent.setup();

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        onSubmit={vi.fn().mockRejectedValue(new Error("network"))}
      />,
    );

    await user.click(screen.getByRole("button", { name: "提交给专家审核" }));
    expect(await screen.findByText(/任务进度已保留/)).toBeInTheDocument();
    expect(localStorage.getItem("dclaw:aigc-guide:task-1:step")).toBe("1");
    control.remove();
  });
});
