import { Modal } from "antd";
import { ApprovalCard } from "./ApprovalCard";

export interface ApprovalDialogRequest {
  requestId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
  agentId: string;
  ownerAgentId?: string;
  sessionId?: string;
  rootSessionId?: string;
}

export interface ApprovalDialogProps {
  requests: ReadonlyMap<string, ApprovalDialogRequest>;
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancelTask?: (request: ApprovalDialogRequest) => void;
}

function getOldestApproval(
  requests: ReadonlyMap<string, ApprovalDialogRequest>,
): ApprovalDialogRequest | null {
  let oldest: ApprovalDialogRequest | null = null;
  for (const request of requests.values()) {
    if (
      oldest === null ||
      request.createdAt < oldest.createdAt ||
      (request.createdAt === oldest.createdAt &&
        request.requestId.localeCompare(oldest.requestId) < 0)
    ) {
      oldest = request;
    }
  }
  return oldest;
}

export function ApprovalDialog({
  requests,
  onApprove,
  onDeny,
  onCancelTask,
}: ApprovalDialogProps) {
  const request = getOldestApproval(requests);

  if (!request) return null;

  return (
    <Modal
      open
      closable={false}
      footer={null}
      width={560}
      centered
      maskClosable={false}
      keyboard={false}
      destroyOnHidden
      zIndex={2000}
      styles={{
        content: {
          padding: 0,
          background: "transparent",
          boxShadow: "none",
        },
      }}
    >
      <div data-approval-id={request.requestId}>
        <ApprovalCard
          requestId={request.requestId}
          agentId={request.agentId}
          ownerAgentId={request.ownerAgentId}
          toolName={request.toolName}
          severity={request.severity}
          findingsCount={request.findingsCount}
          findingsSummary={request.findingsSummary}
          toolParams={request.toolParams}
          createdAt={request.createdAt}
          timeoutSeconds={request.timeoutSeconds}
          sessionId={request.sessionId}
          rootSessionId={request.rootSessionId}
          showParamsExpanded
          onApprove={onApprove}
          onDeny={onDeny}
          onCancel={onCancelTask ? () => onCancelTask(request) : undefined}
        />
      </div>
    </Modal>
  );
}
