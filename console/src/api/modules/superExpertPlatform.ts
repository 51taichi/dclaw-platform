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
  binding: {
    installation_id: string;
    conversation_id: string;
    material_task_id: string;
    canvas_id: string;
    node_id: string;
    [key: string]: unknown;
  };
  status: string;
  asset_id?: string | null;
  operation_id?: string | null;
  operation_version?: string | null;
  operation_arguments?: Record<string, unknown>;
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
  command: (capability: string, command: SuperExpertPlatformCommand) =>
    request<SuperExpertPlatformCommandResult>(
      `/super-expert-platform/commands/${encodeURIComponent(capability)}`,
      {
        method: "POST",
        body: JSON.stringify(command),
      },
    ),
};
