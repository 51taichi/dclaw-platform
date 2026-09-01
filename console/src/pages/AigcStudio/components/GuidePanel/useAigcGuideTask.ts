import { useEffect, useMemo, useState } from "react";
import {
  superExpertPlatformApi,
  type AigcOperationContract,
  type BoundAigcTask,
} from "../../../../api/modules/superExpertPlatform";

const OPERATION_ID = "aigc.text_to_video.create";

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
    Promise.all([
      superExpertPlatformApi.getTask(taskId),
      superExpertPlatformApi.getOperation(OPERATION_ID),
    ])
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

  return { taskId, task, operation, error, loading };
}
