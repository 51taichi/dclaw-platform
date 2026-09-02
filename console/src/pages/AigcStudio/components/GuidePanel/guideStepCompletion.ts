import type { AigcCanvas, AigcJob } from "../../../../api/modules/aigcStudio";
import type { BoundAigcTask } from "../../../../api/modules/superExpertPlatform";

const EMPTY_COMPLETION: Record<string, boolean> = {
  "open-studio": false,
  "create-project": false,
  "add-video-node": false,
  "enter-prompt": false,
  "select-model": false,
  "select-ratio": false,
  "select-duration": false,
  "generate-video": false,
  "verify-result": false,
};

export function getAigcGuideStepCompletion({
  task,
  activeCanvas,
  jobs,
}: {
  task: BoundAigcTask;
  activeCanvas: AigcCanvas | null;
  jobs: AigcJob[];
}): Record<string, boolean> {
  if (!activeCanvas || activeCanvas.id !== task.binding.canvas_id) {
    return { ...EMPTY_COMPLETION };
  }
  const node = activeCanvas.nodes.find(
    (item) => item.id === task.binding.node_id,
  );
  const argumentsValue = task.operation_arguments ?? {};
  const prompt = String(argumentsValue.prompt ?? "");
  const requestedModel = String(argumentsValue.model_id ?? "");
  const requestedRatio = String(argumentsValue.aspect_ratio ?? "");
  const requestedDuration = Number(argumentsValue.duration_seconds);
  const actualModel = String(node?.data.modelId ?? "");
  const boundJobs = jobs.filter(
    (job) =>
      job.canvas_id === task.binding.canvas_id &&
      job.node_id === task.binding.node_id,
  );
  const hasStartedJob = boundJobs.some((job) =>
    ["queued", "running", "succeeded"].includes(job.status),
  );
  const nodeOutputs = Array.isArray(node?.data.outputs)
    ? node.data.outputs
    : [];
  const hasResult =
    nodeOutputs.length > 0 ||
    boundJobs.some(
      (job) => job.status === "succeeded" && job.outputs.length > 0,
    );

  return {
    "open-studio": true,
    "create-project": true,
    "add-video-node": node?.type === "video_generate",
    "enter-prompt": Boolean(node && prompt && node.data.text === prompt),
    "select-model": Boolean(
      node &&
        actualModel &&
        (requestedModel === "auto"
          ? actualModel !== "auto"
          : actualModel === requestedModel),
    ),
    "select-ratio": Boolean(
      node && requestedRatio && node.data.aspectRatio === requestedRatio,
    ),
    "select-duration": Boolean(
      node &&
        Number.isFinite(requestedDuration) &&
        Number(node.data.videoDuration) === requestedDuration,
    ),
    "generate-video": hasStartedJob,
    "verify-result": hasResult,
  };
}
