import { useCallback, useEffect, useMemo, useState } from "react";
import {
  superExpertPlatformApi,
  type AigcGuideProjection,
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
  const [guide, setGuide] = useState<AigcGuideProjection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(taskId));

  const load = useCallback(async () => {
    if (!taskId) return { task: null, guide: null, operation: null };
    const nextTask = await superExpertPlatformApi.getTask(taskId);
    const legacy =
      nextTask.binding.execution_mode === "LEGACY" ||
      !nextTask.binding.workflow_id;
    if (legacy) {
      const operationId = nextTask.operation_id?.trim();
      if (!operationId) {
        throw new Error("当前素材任务没有绑定 AIGC 操作，请从会话重新创建");
      }
      return {
        task: nextTask,
        guide: null,
        operation: await superExpertPlatformApi.getOperation(operationId),
      };
    }
    return {
      task: nextTask,
      guide: await superExpertPlatformApi.getGuide(taskId),
      operation: null,
    };
  }, [taskId]);

  const refresh = useCallback(async () => {
    if (!taskId) return null;
    setError(null);
    const next = await load();
    setTask(next.task);
    setGuide(next.guide);
    setOperation(next.operation);
    return next;
  }, [load, taskId]);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setGuide(null);
      setOperation(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    load()
      .then((next) => {
        if (!active) return;
        setTask(next.task);
        setGuide(next.guide);
        setOperation(next.operation);
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
  }, [load, taskId]);

  useEffect(() => {
    if (guide?.current_step?.status !== "RUNNING") return;
    const timer = window.setTimeout(() => {
      void refresh().catch((reason) => {
        setError(reason instanceof Error ? reason.message : "向导刷新失败");
      });
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [guide?.current_step?.status, guide?.current_step_id, refresh]);

  return {
    taskId,
    task,
    guide,
    operation,
    error,
    loading,
    refresh,
    refreshTask: refresh,
  };
}
