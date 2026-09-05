import type { AigcCanvas, AigcJob } from "../../../../api/modules/aigcStudio";
import type { BoundAigcTask } from "../../../../api/modules/superExpertPlatform";

export function getAigcGuideStepCompletion({
  task,
  activeCanvas,
  jobs,
}: {
  task: BoundAigcTask;
  activeCanvas: AigcCanvas | null;
  jobs: AigcJob[];
}): Record<string, boolean> {
  if (!activeCanvas || activeCanvas.id !== task.binding.canvas_id) return {};
  const node = activeCanvas.nodes.find((item) => item.id === task.binding.node_id);
  const args = task.operation_arguments ?? {};
  const prompt = String(args.prompt ?? "");
  const requestedModel = String(args.model_id ?? "");
  const actualModel = String(node?.data.modelId ?? "");
  const boundJobs = jobs.filter(
    (job) =>
      job.canvas_id === task.binding.canvas_id &&
      job.node_id === task.binding.node_id,
  );
  const outputs = Array.isArray(node?.data.outputs) ? node.data.outputs : [];
  return {
    "open-studio": true,
    "create-project": true,
    "add-video-node": node?.type === "video_generate",
    "enter-prompt": Boolean(node && prompt && node.data.text === prompt),
    "select-model": Boolean(
      node && actualModel &&
        (requestedModel === "auto" ? actualModel !== "auto" : actualModel === requestedModel),
    ),
    "select-ratio": Boolean(node && node.data.aspectRatio === args.aspect_ratio),
    "select-duration": Boolean(
      node && Number(node.data.videoDuration) === Number(args.duration_seconds),
    ),
    "generate-video": boundJobs.some((job) =>
      ["queued", "running", "succeeded"].includes(job.status),
    ),
    "verify-result":
      outputs.length > 0 ||
      boundJobs.some((job) => job.status === "succeeded" && job.outputs.length > 0),
  };
}
