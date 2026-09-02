import { useCallback, useEffect, useMemo, useState } from "react";
import {
  superExpertPlatformApi,
  type AigcOperationContract,
  type BoundAigcTask,
} from "../../../../api/modules/superExpertPlatform";

export function useAigcGuideTask(search: string) {
  const taskId = useMemo(
    () => new URLSearchParams(search).get("task")?.trim() || null,
    [search],
  );
  const [task, setTask] = useState<BoundAigcTask | null>(null);
  const [operation, setOperation] = useState<AigcOperationContract | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(taskId));

  const refreshTask = useCallback(async () => {
    if (!taskId) return null;
    const nextTask = await superExpertPlatformApi.getTask(taskId);
    setTask(nextTask);
    return nextTask;
  }, [taskId]);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setOperation(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    superExpertPlatformApi
      .getTask(taskId)
      .then(async (nextTask) => {
        const operationId = nextTask.operation_id?.trim();
        if (!operationId) {
          throw new Error("当前素材任务没有绑定 AIGC 操作，请从会话重新创建");
        }
        const nextOperation =
          await superExpertPlatformApi.getOperation(operationId);
        return [nextTask, nextOperation] as const;
      })
      .then(([nextTask, nextOperation]) => {
        if (!active) return;
        setTask(nextTask);
        setOperation(nextOperation);
      })
      .catch((reason) => {
        if (active)
          setError(reason instanceof Error ? reason.message : "向导加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [taskId]);

  return { taskId, task, operation, error, loading, refreshTask };
}
