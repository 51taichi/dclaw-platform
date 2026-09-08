import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { superExpertPlatformApi } from "../../api/modules/superExpertPlatform";
import { useGuidedTaskReturn } from "./useGuidedTaskReturn";
vi.mock("../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: { getConversationRoute: vi.fn() },
}));
const task = {
  status: "IN_PROGRESS",
  binding: {
    installation_id: "i",
    conversation_id: "internal",
    material_task_id: "m",
    canvas_id: "c",
    node_id: "n",
  },
};
it("does not redirect after leaving Studio during a delayed route lookup", async () => {
  let finish!: (
    value: Awaited<
      ReturnType<typeof superExpertPlatformApi.getConversationRoute>
    >,
  ) => void;
  vi.mocked(superExpertPlatformApi.getConversationRoute).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const navigate = vi.fn();
  const view = renderHook(() => useGuidedTaskReturn(task, navigate));
  let pending!: Promise<void>;
  act(() => {
    pending = view.result.current();
  });
  view.unmount();
  finish({ conversation_id: "internal", chat_id: "public", agent_id: "luyu" });
  await pending;
  expect(navigate).not.toHaveBeenCalled();
});
it("does not run an old submission's return callback after changing tasks", async () => {
  const navigate = vi.fn();
  const view = renderHook(
    ({ current }) => useGuidedTaskReturn(current, navigate),
    { initialProps: { current: task } },
  );
  const old = view.result.current;
  view.rerender({
    current: { ...task, binding: { ...task.binding, material_task_id: "new" } },
  });
  await old();
  expect(navigate).not.toHaveBeenCalled();
});
