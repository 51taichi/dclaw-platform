import type { BoundAigcTask } from "../../api/modules/superExpertPlatform";
import { useEffect, useMemo } from "react";
import { getGuidedConversationRoute } from "./guidedTaskActions";
export function useGuidedTaskReturn(
  task: BoundAigcTask | null,
  navigate: (path: string) => void,
) {
  const taskLifetimeKey = task
    ? `${task.binding.material_task_id}:${task.binding.conversation_id}`
    : "";
  const lifetime = useMemo(
    () => ({ active: true, taskLifetimeKey }),
    [taskLifetimeKey],
  );
  useEffect(() => {
    lifetime.active = true;
    return () => {
      lifetime.active = false;
    };
  }, [lifetime]);
  return async () => {
    if (!task || !lifetime.active) return;
    const route = await getGuidedConversationRoute(task);
    if (lifetime.active) navigate(route);
  };
}
