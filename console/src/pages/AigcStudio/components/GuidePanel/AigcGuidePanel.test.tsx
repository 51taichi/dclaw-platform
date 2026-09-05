import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcGuideProjection,
  BoundAigcTask,
} from "../../../../api/modules/superExpertPlatform";
import { AigcGuidePanel } from "./AigcGuidePanel";

const fullPrompt = "失业人群免费参加抖音运营培训，真实课堂，竖屏纪实。";
const task: BoundAigcTask = {
  binding: {
    installation_id: "installation-1",
    conversation_id: "conversation-1",
    material_task_id: "task-1",
    canvas_id: "canvas-1",
    node_id: "video-physical-1",
    workflow_id: "workflow-1",
    execution_mode: "PREBUILT_WORKFLOW",
    output_node_id: "video-physical-1",
  },
  status: "WAITING_TO_START",
  operation_arguments: {
    project_name: "天门就业培训",
    prompt: fullPrompt,
    aspect_ratio: "9:16",
    duration_seconds: 5,
  },
};

const readyGuide: AigcGuideProjection = {
  workflow_id: "workflow-1",
  workflow_revision: 1,
  guide_revision: 1,
  execution_mode: "PREBUILT_WORKFLOW",
  current_step_id: "clip.generate",
  current_step: {
    step_id: "clip.generate",
    kind: "GENERATE",
    title: "生成痛点开场视频",
    instruction: "检查参数后，点击当前视频节点的生成按钮。",
    logical_node_id: "clip",
    node_id: "video-physical-1",
    control_id: "aigc.video.generate-submit",
    optional: false,
    status: "READY",
    recovery: null,
  },
  steps: [
    {
      step_id: "copy.generate",
      kind: "GENERATE",
      title: "生成痛点文案",
      instruction: "点击生成",
      logical_node_id: "copy",
      node_id: "prompt-physical-1",
      control_id: "aigc.text.generate-submit",
      optional: false,
      status: "COMPLETED",
      recovery: null,
    },
  ],
  task_summary: {
    material_task_id: "task-1",
    status: "WAITING_TO_START",
    asset_id: null,
    task_version: 1,
  },
};

describe("AigcGuidePanel", () => {
  it("renders the current action before collapsed task parameters", () => {
    render(
      <AigcGuidePanel task={task} guide={readyGuide} activeCanvasId="canvas-1" />,
    );

    const current = screen.getByRole("heading", {
      name: "生成痛点开场视频",
    });
    const parameters = screen.getByText("查看任务参数");
    expect(
      current.compareDocumentPosition(parameters) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText(fullPrompt)).not.toBeVisible();
  });

  it("focuses the physical node and never renders a duplicate generate button", async () => {
    const onFocusStep = vi.fn();
    const user = userEvent.setup();
    render(
      <AigcGuidePanel
        task={task}
        guide={readyGuide}
        activeCanvasId="canvas-1"
        onFocusStep={onFocusStep}
      />,
    );

    await user.click(screen.getByRole("button", { name: "定位到生成按钮" }));

    expect(onFocusStep).toHaveBeenCalledWith(
      "video-physical-1",
      "aigc.video.generate-submit",
    );
    expect(
      screen.queryByRole("button", { name: "开始生成" }),
    ).not.toBeInTheDocument();
  });

  it("does not render create-node instructions for prebuilt mode", () => {
    render(
      <AigcGuidePanel task={task} guide={readyGuide} activeCanvasId="canvas-1" />,
    );

    expect(
      screen.queryByText(/新建项目|添加视频生成节点|粘贴提示词/),
    ).not.toBeInTheDocument();
  });

  it("offers skip only for an optional current step", async () => {
    const onSkipOptional = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <AigcGuidePanel
        task={task}
        guide={{
          ...readyGuide,
          current_step: { ...readyGuide.current_step!, optional: true },
        }}
        activeCanvasId="canvas-1"
        onSkipOptional={onSkipOptional}
      />,
    );

    await user.click(screen.getByRole("button", { name: "跳过这个可选步骤" }));
    expect(onSkipOptional).toHaveBeenCalledWith(
      expect.objectContaining({ step_id: "clip.generate" }),
    );
  });

  it("shows server recovery and blocks unrelated canvases", () => {
    render(
      <AigcGuidePanel
        task={task}
        guide={{
          ...readyGuide,
          current_step: {
            ...readyGuide.current_step!,
            status: "BLOCKED",
            recovery: {
              action: "RESTORE_BOUND_CANVAS",
              code: "BOUND_CANVAS_MISSING",
            },
          },
        }}
        activeCanvasId="canvas-other"
      />,
    );

    expect(screen.getByText(/不属于此任务/)).toBeInTheDocument();
    expect(screen.getByText(/BOUND_CANVAS_MISSING/)).toBeInTheDocument();
  });

  it("executes one server-defined manual build action at a time", async () => {
    const onManualBuild = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    const manualStep = {
      ...readyGuide.current_step!,
      step_id: "compose.manual-add",
      kind: "MANUAL_BUILD" as const,
      status: "READY" as const,
      manual_action: "ADD_NODE" as const,
      node_kind: "video_compose",
    };
    render(
      <AigcGuidePanel
        task={task}
        guide={{
          ...readyGuide,
          execution_mode: "MANUAL_BUILD",
          current_step_id: manualStep.step_id,
          current_step: manualStep,
          steps: [manualStep],
        }}
        activeCanvasId="canvas-1"
        onManualBuild={onManualBuild}
      />,
    );

    await user.click(screen.getByRole("button", { name: "添加此节点" }));
    expect(onManualBuild).toHaveBeenCalledWith(manualStep);
  });
});
