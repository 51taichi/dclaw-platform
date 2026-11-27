import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAigcGuideTask } from "./useAigcGuideTask";

const api = vi.hoisted(() => ({
  getTask: vi.fn(),
  getGuide: vi.fn(),
  getOperation: vi.fn(),
  command: vi.fn(),
}));

vi.mock("../../../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: api,
}));

const workflowTask = {
  binding: {
    installation_id: "installation-1",
    conversation_id: "conversation-1",
    agent_task_id: "content-1",
    content_revision: 1,
    material_task_id: "task-1",
    canvas_id: "canvas-1",
    node_id: "video-1",
    workflow_id: "workflow-1",
    execution_mode: "PREBUILT_WORKFLOW",
    node_bindings: { copy: "prompt-1", clip: "video-1" },
    output_node_id: "video-1",
    workflow_revision: 1,
    guide_revision: 1,
  },
  status: "WAITING_TO_START",
  version: 1,
  events: [],
  workflow: { workflow_id: "workflow-1" },
  guide_events: [],
};

const guide = (currentStepId: string) => ({
  workflow_id: "workflow-1",
  workflow_revision: 1,
  guide_revision: 1,
  execution_mode: "PREBUILT_WORKFLOW",
  current_step_id: currentStepId,
  current_step: {
    step_id: currentStepId,
    kind: "GENERATE",
    title: currentStepId,
    instruction: "点击生成",
    logical_node_id: currentStepId.startsWith("copy") ? "copy" : "clip",
    node_id: currentStepId.startsWith("copy") ? "prompt-1" : "video-1",
    control_id: "aigc.text.generate-submit",
    optional: false,
    status: "READY",
    recovery: null,
  },
  steps: [],
  task_summary: {
    material_task_id: "task-1",
    status: "WAITING_TO_START",
    asset_id: null,
    task_version: 1,
  },
});

describe("useAigcGuideTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.command.mockResolvedValue({
      task: { ...workflowTask, status: "IN_PROGRESS" },
    });
  });

  it("starts a waiting task opened by direct link without invoking a generation job", async () => {
    api.getTask.mockResolvedValue(workflowTask);
    api.getGuide.mockResolvedValue(guide("copy.generate"));
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.task?.status).toBe("IN_PROGRESS");
    expect(api.command).toHaveBeenCalledTimes(1);
    expect(api.command).toHaveBeenCalledWith(
      "aigc.task.resume",
      expect.objectContaining({
        installation_id: "installation-1",
        arguments: expect.objectContaining({ binding: workflowTask.binding }),
      }),
    );
  });

  it("keeps the latest revision feedback after automatically resuming the task", async () => {
    const reviewedTask = {
      ...workflowTask,
      status: "REVISION_REQUIRED",
      latest_review: {
        decision: "REVISION_REQUIRED",
        assessment: "请修改封面列出的三项内容。",
      },
    };
    api.getTask.mockResolvedValue(reviewedTask);
    api.getGuide.mockResolvedValue(guide("copy.generate"));
    api.command.mockResolvedValue({
      task: { ...workflowTask, status: "IN_PROGRESS" },
    });

    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.task?.status).toBe("IN_PROGRESS");
    expect(result.current.task?.latest_review?.assessment).toBe(
      "请修改封面列出的三项内容。",
    );
    expect(api.getTask).toHaveBeenCalledTimes(1);
  });

  it("loads the task and instance guide without requesting a static operation", async () => {
    api.getTask.mockResolvedValue(workflowTask);
    api.getGuide.mockResolvedValue(guide("copy.generate"));

    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.guide?.current_step_id).toBe("copy.generate");
    expect(api.getGuide).toHaveBeenCalledWith("task-1");
    expect(api.getOperation).not.toHaveBeenCalled();
  });

  it("reloads the authoritative task and step after refresh", async () => {
    api.getTask.mockResolvedValue(workflowTask);
    api.getGuide
      .mockResolvedValueOnce(guide("copy.generate"))
      .mockResolvedValueOnce(guide("clip.generate"));
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.guide?.current_step_id).toBe("clip.generate");
    expect(api.getTask).toHaveBeenCalledTimes(2);
    expect(api.getGuide).toHaveBeenCalledTimes(2);
  });

  it("uses the static operation contract only for a legacy task", async () => {
    const legacyTask = {
      ...workflowTask,
      binding: {
        ...workflowTask.binding,
        workflow_id: null,
        execution_mode: "LEGACY",
      },
      workflow: null,
      operation_id: "aigc.text_to_video.create",
    };
    api.getTask.mockResolvedValue(legacyTask);
    api.command.mockResolvedValue({
      task: { ...legacyTask, status: "IN_PROGRESS" },
    });
    api.getOperation.mockResolvedValue({
      operation_id: "aigc.text_to_video.create",
      version: "1",
      title: "旧版视频",
      human_guide: [],
    });

    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.operation?.operation_id).toBe(
      "aigc.text_to_video.create",
    );
    expect(api.getGuide).not.toHaveBeenCalled();
  });

  it("does not resume on read-only refresh or when the task is already running", async () => {
    api.getTask.mockResolvedValue({ ...workflowTask, status: "IN_PROGRESS" });
    api.getGuide.mockResolvedValue(guide("copy.generate"));
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.getTask.mockResolvedValue({ ...workflowTask, status: "PAUSED" });
    await act(async () => {
      await result.current.refresh();
    });
    expect(api.command).not.toHaveBeenCalled();
    expect(result.current.task?.status).toBe("PAUSED");
  });

  it("does not start a task when its entry was unmounted during loading", async () => {
    let resolveTask!: (task: typeof workflowTask) => void;
    api.getTask.mockReturnValue(
      new Promise((resolve) => {
        resolveTask = resolve;
      }),
    );
    api.getGuide.mockResolvedValue(guide("copy.generate"));
    const { unmount } = renderHook(() => useAigcGuideTask("?task=task-1"));
    unmount();
    await act(async () => {
      resolveTask(workflowTask);
    });
    expect(api.command).not.toHaveBeenCalled();
  });

  it("reports a failed start instead of pretending the guide is ready", async () => {
    api.getTask.mockResolvedValue(workflowTask);
    api.command.mockRejectedValue(new Error("start failed"));
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("start failed");
    expect(result.current.task).toBeNull();
    expect(api.getGuide).not.toHaveBeenCalled();
  });

  it("accepts a concurrent start only after verifying persisted running status", async () => {
    api.getTask
      .mockResolvedValueOnce(workflowTask)
      .mockResolvedValue({ ...workflowTask, status: "IN_PROGRESS" });
    api.command.mockRejectedValue(new Error("already started"));
    api.getGuide.mockResolvedValue(guide("copy.generate"));
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.task?.status).toBe("IN_PROGRESS");
  });

  it("polls authoritative state while the current workflow step is running", async () => {
    api.getTask.mockResolvedValue(workflowTask);
    api.getGuide
      .mockResolvedValueOnce({
        ...guide("clip.generate"),
        current_step: {
          ...guide("clip.generate").current_step,
          status: "RUNNING",
        },
      })
      .mockResolvedValueOnce({
        ...guide("clip.generate"),
        current_step: {
          ...guide("clip.generate").current_step,
          status: "RUNNING",
        },
      })
      .mockResolvedValueOnce({
        ...guide("workflow.submit"),
        current_step: {
          ...guide("workflow.submit").current_step,
          kind: "SUBMIT",
          status: "READY",
        },
      });
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await waitFor(
      () =>
        expect(result.current.guide?.current_step_id).toBe("workflow.submit"),
      { timeout: 4500 },
    );
    expect(api.getGuide).toHaveBeenCalledTimes(3);
  });

  it("keeps polling after one transient guide refresh failure", async () => {
    api.getTask.mockResolvedValue(workflowTask);
    api.getGuide
      .mockResolvedValueOnce({
        ...guide("clip.generate"),
        current_step: {
          ...guide("clip.generate").current_step,
          status: "RUNNING",
        },
      })
      .mockRejectedValueOnce(new Error("temporary network error"))
      .mockResolvedValueOnce({
        ...guide("workflow.submit"),
        current_step: {
          ...guide("workflow.submit").current_step,
          kind: "SUBMIT",
          status: "READY",
        },
      });
    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await waitFor(
      () =>
        expect(result.current.guide?.current_step_id).toBe("workflow.submit"),
      { timeout: 4500 },
    );
    expect(api.getGuide).toHaveBeenCalledTimes(3);
  });
});
