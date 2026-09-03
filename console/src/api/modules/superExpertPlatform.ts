import { request } from "../request";

export interface SuperExpertPlatformCommand {
  installation_id: string;
  contract_version: "1";
  idempotency_key: string;
  arguments: Record<string, unknown>;
}

export interface AigcGuideStep {
  step_id: string;
  title: string;
  instruction: string;
  control_id: string;
  action: "click" | "input" | "select" | "wait" | "verify";
  success_signal: string;
  recovery: string;
}

export interface AigcOperationContract {
  operation_id: string;
  version: "1";
  title: string;
  human_guide: AigcGuideStep[];
}

export interface BoundAigcTask {
  binding: AigcWorkflowBinding;
  status: string;
  asset_id?: string | null;
  version?: number;
  events?: Record<string, unknown>[];
  workflow?: Record<string, unknown> | null;
  guide_events?: Record<string, unknown>[];
  operation_id?: string | null;
  operation_version?: string | null;
  operation_arguments?: Record<string, unknown>;
}

export interface AigcWorkflowBinding {
  installation_id: string;
  conversation_id: string;
  agent_task_id?: string;
  content_revision?: number;
  material_task_id: string;
  canvas_id: string;
  node_id: string;
  workflow_id?: string | null;
  execution_mode?: "LEGACY" | "PREBUILT_WORKFLOW" | "MANUAL_BUILD";
  node_bindings?: Record<string, string>;
  output_node_id?: string | null;
  workflow_revision?: number | null;
  guide_revision?: number | null;
}

export type GuideStepStatus =
  | "LOCKED"
  | "READY"
  | "RUNNING"
  | "FAILED"
  | "COMPLETED"
  | "SKIPPED"
  | "BLOCKED";

export interface AigcGuideRecovery {
  action: "RETRY_NODE" | "RESTORE_BOUND_CANVAS" | "RELOAD_TASK";
  code: string;
}

export interface AigcGuideStepProjection {
  step_id: string;
  kind: "INSPECT" | "GENERATE" | "SUBMIT" | "MANUAL_BUILD";
  title: string;
  instruction: string;
  logical_node_id: string | null;
  node_id: string | null;
  control_id: string | null;
  optional: boolean;
  status: GuideStepStatus;
  recovery: AigcGuideRecovery | null;
}

export interface AigcGuideProjection {
  workflow_id: string;
  workflow_revision: number;
  guide_revision: number;
  execution_mode: "PREBUILT_WORKFLOW" | "MANUAL_BUILD";
  current_step_id: string | null;
  current_step: AigcGuideStepProjection | null;
  steps: AigcGuideStepProjection[];
  task_summary: {
    material_task_id: string;
    status: string;
    asset_id: string | null;
    task_version: number;
  };
}

export interface SuperExpertPlatformCommandResult {
  event?: Record<string, unknown>;
  task?: BoundAigcTask;
  card?: Record<string, unknown>;
  agent_review?: {
    status: "completed";
    reply: string;
  };
}

export const superExpertPlatformApi = {
  getTask: (materialTaskId: string) =>
    request<BoundAigcTask>(
      `/super-expert-platform/tasks/${encodeURIComponent(materialTaskId)}`,
    ),
  getOperation: (operationId: string) =>
    request<AigcOperationContract>(
      `/super-expert-platform/operations/${encodeURIComponent(operationId)}`,
    ),
  getGuide: (materialTaskId: string) =>
    request<AigcGuideProjection>(
      `/super-expert-platform/tasks/${encodeURIComponent(materialTaskId)}/guide`,
    ),
  command: (capability: string, command: SuperExpertPlatformCommand) =>
    request<SuperExpertPlatformCommandResult>(
      `/super-expert-platform/commands/${encodeURIComponent(capability)}`,
      {
        method: "POST",
        body: JSON.stringify(command),
      },
    ),
};
