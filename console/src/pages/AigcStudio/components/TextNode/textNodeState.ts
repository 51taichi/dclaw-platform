import type {
  AigcCanvasNode,
  AigcJob,
} from "../../../../api/modules/aigcStudio";

export type TextNodeState = "idle" | "generating" | "generated" | "failed";

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

export function textFromJobOutput(job: AigcJob) {
  for (const output of job.outputs) {
    const text = textValue(output.meta?.text);
    if (text) return text;
  }
  return "";
}

export function textNodeStateFromNode(node: AigcCanvasNode): TextNodeState {
  const explicitState = textValue(node.data.textState);
  if (
    explicitState === "idle" ||
    explicitState === "generating" ||
    explicitState === "generated" ||
    explicitState === "failed"
  ) {
    return explicitState;
  }

  const jobStatus = textValue(node.data.job_status);
  if (jobStatus === "queued" || jobStatus === "running") return "generating";
  if (jobStatus === "failed" || jobStatus === "cancelled") return "failed";
  if (jobStatus === "succeeded") return "generated";
  return textValue(node.data.text) ? "generated" : "idle";
}
