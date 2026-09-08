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

  const load = useCallback(
    async (startOnEntry = false, isActive: () => boolean = () => true) => {
      if (!taskId) return { task: null, guide: null, operation: null };
      let nextTask = await superExpertPlatformApi.getTask(taskId);
      // Opening a task starts its guide, never a paid generation job. Polling is read-only.
      if (
        startOnEntry &&
        isActive() &&
        ["WAITING_TO_START", "PAUSED", "REVISION_REQUIRED"].includes(
          nextTask.status,
        )
      ) {
        const eventId = crypto.randomUUID();
        try {
          const resumed = await superExpertPlatformApi.command(
            "aigc.task.resume",
            {
              installation_id: nextTask.binding.installation_id,
              contract_version: "1",
              idempotency_key: eventId,
              arguments: { event_id: eventId, binding: nextTask.binding },
            },
          );
          nextTask =
            resumed.task ?? (await superExpertPlatformApi.getTask(taskId));
        } catch (reason) {
          // Another tab may already have started this task. Verify, never assume success.
          const latest = await superExpertPlatformApi.getTask(taskId);
          if (latest.status !== "IN_PROGRESS") throw reason;
          nextTask = latest;
        }
      }
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
    },
    [taskId],
  );

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
    load(true, () => active)
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
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await refresh();
        if (active && next?.guide?.current_step?.status === "RUNNING") {
          timer = window.setTimeout(poll, 1200);
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "向导刷新失败");
          timer = window.setTimeout(poll, 1200);
        }
      }
    };
    timer = window.setTimeout(poll, 1200);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
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
