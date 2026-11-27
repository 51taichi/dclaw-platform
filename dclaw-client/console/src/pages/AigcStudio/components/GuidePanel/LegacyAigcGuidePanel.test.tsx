import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LegacyAigcGuidePanel } from "./LegacyAigcGuidePanel";
const task = {
  status: "IN_PROGRESS",
  binding: {
    installation_id: "i1",
    conversation_id: "c1",
    material_task_id: "m1",
    canvas_id: "cv1",
    node_id: "n1",
  },
};
const operation = {
  operation_id: "op1",
  version: "1" as const,
  title: "制作素材",
  human_guide: [
    {
      step_id: "submit",
      title: "提交素材",
      instruction: "提交成品",
      control_id: "submit",
      action: "click" as const,
      success_signal: "提交成功",
      recovery: "等待生成",
    },
  ],
};
beforeEach(() => localStorage.clear());
it("keeps icon-labelled footer actions outside the scrollable instructions", () => {
  render(
    <LegacyAigcGuidePanel
      taskId="m1"
      task={task}
      operation={operation}
      stepCompletion={{}}
      onReturnToChat={() => {}}
    />,
  );
  const content = screen.getByRole("region", { name: "向导内容" });
  expect(content).toHaveAttribute("tabindex", "0");
  for (const name of ["返回任务会话", "暂停向导", "完成并返回会话"]) {
    const button = screen.getByRole("button", { name });
    expect(content).not.toContainElement(button);
    expect(button.querySelector("svg")).not.toBeNull();
  }
});
it("offers return before completion", async () => {
  const back = vi.fn();
  render(
    <LegacyAigcGuidePanel
      taskId="m1"
      task={task}
      operation={operation}
      stepCompletion={{}}
      onReturnToChat={back}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "返回任务会话" }));
  await waitFor(() => expect(back).toHaveBeenCalledOnce());
});
it.each([true, false])(
  "only returns after successful submission: %s",
  async (success) => {
    const back = vi.fn();
    render(
      <LegacyAigcGuidePanel
        taskId="m1"
        task={task}
        operation={operation}
        stepCompletion={{ submit: true }}
        onSubmit={async () => success}
        onReturnToChat={back}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "完成并返回会话" }));
    if (success) await waitFor(() => expect(back).toHaveBeenCalledOnce());
    else {
      await screen.findByRole("alert");
      expect(back).not.toHaveBeenCalled();
    }
  },
);
it("lets a submitted legacy task retry review", async () => {
  const submit = vi.fn().mockResolvedValue(true);
  const back = vi.fn();
  render(
    <LegacyAigcGuidePanel
      taskId="m1"
      task={{ ...task, status: "SUBMITTED" }}
      operation={operation}
      stepCompletion={{ submit: true }}
      onSubmit={submit}
      onReturnToChat={back}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "完成并返回会话" }));

  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  expect(back).toHaveBeenCalledOnce();
});
