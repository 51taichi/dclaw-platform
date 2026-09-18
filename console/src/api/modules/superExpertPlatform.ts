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
  review_assets?: { node_id: string; asset_id: string }[];
  version?: number;
  events?: Record<string, unknown>[];
  workflow?: Record<string, unknown> | null;
  guide_events?: Record<string, unknown>[];
  operation_id?: string | null;
  operation_version?: string | null;
  operation_arguments?: Record<string, unknown>;
  latest_review?: {
    decision: "ACCEPTED" | "REVISION_REQUIRED";
    assessment: string;
  } | null;
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
  manual_action?: "ADD_NODE" | "CONNECT_EDGE" | null;
  node_kind?: string | null;
  source_node_id?: string | null;
  target_node_id?: string | null;
  target_slot?: string | null;
  manual_node_data?: Record<string, unknown> | null;
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
    status: "completed" | "model_required" | "review_incomplete";
    reply: string;
    required_modalities?: Array<"image" | "video">;
  };
}

export type InteractionStatus =
  | "PENDING"
  | "SUBMITTED"
  | "CANCELLED"
  | "REPLACED"
  | "EXPIRED";
export type InteractionInputPolicy =
  | "card_only"
  | "card_or_text"
  | "concurrent";

export interface InteractionOption {
  id: string | null;
  text: string;
  description: string | null;
  recommended: boolean;
  default_selected: boolean;
}

export interface InteractionSupplement {
  enabled: boolean;
  label: string;
  placeholder: string;
  required: boolean;
  max_length: number;
}

export interface ChoiceInteractionAnswer {
  selected: Array<{ id: string | null; text: string }>;
  supplement: string | null;
  answers?: never;
}

export interface QuestionFormInteractionAnswer {
  answers: Array<{
    id: string | null;
    question: string;
    value: string | null;
  }>;
  selected?: never;
  supplement?: never;
}

interface InteractionCardRecordBase {
  interaction_id: string;
  task_key: string;
  interaction_revision: number;
  input_policy: InteractionInputPolicy;
  status: InteractionStatus;
  version: number;
  binding: {
    installation_id: string;
    conversation_id: string;
    agent_task_id: string;
  };
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChoiceInteractionCardRecord extends InteractionCardRecordBase {
  component_type: "single_select" | "multi_select";
  card: {
    title: string;
    description: string | null;
    options: InteractionOption[];
    supplement: InteractionSupplement;
    layout: "auto" | "list" | "grid";
    min_selections?: number;
    max_selections?: number | null;
  };
  answer: ChoiceInteractionAnswer | null;
}

export interface QuestionFormInteractionCardRecord
  extends InteractionCardRecordBase {
  component_type: "question_form";
  card: {
    title: string;
    description: string | null;
    items: Array<{
      id: string | null;
      question: string;
      description: string | null;
      placeholder: string;
      required: boolean;
      max_length: number;
    }>;
  };
  answer: QuestionFormInteractionAnswer | null;
}

export type InteractionCardRecord =
  | ChoiceInteractionCardRecord
  | QuestionFormInteractionCardRecord;

interface InteractionSubmitPayloadBase {
  version: number;
  idempotency_key: string;
}

export type InteractionSubmitPayload =
  | (InteractionSubmitPayloadBase & {
      selected: Array<{ id?: string; text?: string }>;
      supplement: string | null;
      answers?: never;
    })
  | (InteractionSubmitPayloadBase & {
      answers: Array<{ id?: string; question?: string; value: string | null }>;
      selected?: never;
      supplement?: never;
    });

export const superExpertPlatformApi = {
  getConversationRoute: (conversationId: string) =>
    request<{ conversation_id: string; agent_id: string; chat_id: string }>(
      `/super-expert-platform/conversation-route?conversation_id=${encodeURIComponent(
        conversationId,
      )}`,
    ),
  listCards: (conversationId: string) =>
    request<{
      cards: Array<{
        material_task_id: string;
        title: string;
        instruction: string;
        status: string;
        binding: AigcWorkflowBinding;
        href: string;
      }>;
    }>(
      `/super-expert-platform/cards?conversation_id=${encodeURIComponent(
        conversationId,
      )}`,
    ),
  listInteractions: (conversationId: string) =>
    request<{ interactions: InteractionCardRecord[] }>(
      `/super-expert-platform/interactions?conversation_id=${encodeURIComponent(
        conversationId,
      )}`,
    ),
  submitInteraction: (
    interactionId: string,
    submission: InteractionSubmitPayload,
  ) =>
    request<{
      interaction: InteractionCardRecord;
      user_input: string;
    }>(
      `/super-expert-platform/interactions/${encodeURIComponent(
        interactionId,
      )}/submit`,
      {
        method: "POST",
        body: JSON.stringify(submission),
      },
    ),
  getTask: (materialTaskId: string) =>
    request<BoundAigcTask>(
      `/super-expert-platform/tasks/${encodeURIComponent(materialTaskId)}`,
    ),
  downloadReviewAssets: async (materialTaskId: string) => {
    const blob = await request<Blob>(
      `/super-expert-platform/tasks/${encodeURIComponent(
        materialTaskId,
      )}/review-assets/archive`,
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `审核素材-${materialTaskId}.zip`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
  getOperation: (operationId: string) =>
    request<AigcOperationContract>(
      `/super-expert-platform/operations/${encodeURIComponent(operationId)}`,
    ),
  getGuide: (materialTaskId: string) =>
    request<AigcGuideProjection>(
      `/super-expert-platform/tasks/${encodeURIComponent(
        materialTaskId,
      )}/guide`,
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
