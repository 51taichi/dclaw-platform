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
  operation_id: "aigc.text_to_video.create",
  operation_version: "1",
  operation_arguments: {
    project_name: "天门就业培训",
    prompt: "失业人群免费参加抖音运营培训。",
    model_id: "auto",
    aspect_ratio: "9:16",
    duration_seconds: 5,
  },
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
    document
      .querySelectorAll("[data-platform-control-id]")
      .forEach((element) => element.remove());
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
        stepCompletion={{ "open-studio": true }}
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
        stepCompletion={{ "create-project": true }}
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
        stepCompletion={{ "open-studio": true }}
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
        stepCompletion={{ "create-project": true }}
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
        stepCompletion={{ "create-project": true }}
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
        stepCompletion={{ "create-project": true }}
        onSubmit={vi.fn().mockRejectedValue(new Error("network"))}
      />,
    );

    await user.click(screen.getByRole("button", { name: "提交给专家审核" }));
    expect(await screen.findByText(/任务进度已保留/)).toBeInTheDocument();
    expect(localStorage.getItem("dclaw:aigc-guide:task-1:step")).toBe("1");
    control.remove();
  });

  it("offers one deterministic return to the bound chat after acceptance", async () => {
    localStorage.setItem("dclaw:aigc-guide:task-1:step", "1");
    const control = document.createElement("button");
    control.dataset.platformControlId = "aigc.canvas.create";
    document.body.append(control);
    const onReturnToChat = vi.fn();
    const user = userEvent.setup();

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={{ ...task, status: "ACCEPTED" }}
        operation={operation}
        activeCanvasId="canvas-1"
        stepCompletion={{ "create-project": true }}
        onReturnToChat={onReturnToChat}
      />,
    );

    await user.click(screen.getByRole("button", { name: "返回原会话" }));
    expect(onReturnToChat).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("button", { name: "提交给专家审核" }),
    ).not.toBeInTheDocument();
    control.remove();
  });

  it("does not advance until the current step has machine-verifiable evidence", async () => {
    const user = userEvent.setup();
    const control = document.createElement("button");
    control.dataset.platformControlId = "nav.aigc-studio";
    document.body.append(control);

    const { rerender } = render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        stepCompletion={{ "open-studio": false }}
      />,
    );

    expect(screen.getByText(/尚未检测到完成标志/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本步已完成" })).toBeDisabled();

    rerender(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        stepCompletion={{ "open-studio": true }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "本步已完成" }));
    expect(screen.getByText("创建项目")).toBeInTheDocument();
    control.remove();
  });

  it("recovers from an invalid persisted step instead of rendering NaN", () => {
    localStorage.setItem("dclaw:aigc-guide:task-1:step", "not-a-number");
    const control = document.createElement("button");
    control.dataset.platformControlId = "nav.aigc-studio";
    document.body.append(control);

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        stepCompletion={{ "open-studio": true }}
      />,
    );

    expect(screen.getByText("确认进入工作室")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    control.remove();
  });

  it("ignores hidden duplicate controls and automatically highlights the actionable one", async () => {
    const hidden = document.createElement("button");
    hidden.dataset.platformControlId = "nav.aigc-studio";
    hidden.hidden = true;
    const visible = document.createElement("button");
    visible.dataset.platformControlId = "nav.aigc-studio";
    document.body.append(hidden, visible);

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        stepCompletion={{ "open-studio": true }}
      />,
    );

    await waitFor(() =>
      expect(visible.dataset.platformGuideHighlight).toBe("true"),
    );
    expect(hidden.dataset.platformGuideHighlight).toBeUndefined();
    hidden.remove();
    visible.remove();
  });

  it("shows the exact task parameters produced by the expert", () => {
    const control = document.createElement("button");
    control.dataset.platformControlId = "nav.aigc-studio";
    document.body.append(control);

    render(
      <AigcGuidePanel
        taskId="task-1"
        task={task}
        operation={operation}
        activeCanvasId="canvas-1"
        stepCompletion={{ "open-studio": true }}
      />,
    );

    expect(screen.getByText("天门就业培训")).toBeInTheDocument();
    expect(
      screen.getByText("失业人群免费参加抖音运营培训。"),
    ).toBeInTheDocument();
    expect(screen.getByText("9:16 · 5 秒")).toBeInTheDocument();
    control.remove();
  });
});
