import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAigcGuideTask } from "./useAigcGuideTask";

const api = vi.hoisted(() => ({
  getTask: vi.fn(),
  getOperation: vi.fn(),
}));

vi.mock("../../../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: api,
}));

describe("useAigcGuideTask", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads the operation declared by the bound task instead of a hardcoded operation", async () => {
    api.getTask.mockResolvedValue({
      binding: {
        installation_id: "installation-1",
        conversation_id: "conversation-1",
        material_task_id: "task-1",
        canvas_id: "canvas-1",
        node_id: "node-1",
      },
      status: "IN_PROGRESS",
      operation_id: "aigc.future.operation",
      operation_version: "1",
      operation_arguments: {},
    });
    api.getOperation.mockResolvedValue({
      operation_id: "aigc.future.operation",
      version: "1",
      title: "未来操作",
      human_guide: [],
    });

    const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.getOperation).toHaveBeenCalledWith("aigc.future.operation");
    expect(result.current.operation?.operation_id).toBe(
      "aigc.future.operation",
    );
  });
});
