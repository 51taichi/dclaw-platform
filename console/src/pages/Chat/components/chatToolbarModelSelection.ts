import type { ModelSlotRequest } from "@/api/types";

export const AUTO_ROUTING_PROVIDER_ID = "auto";
export const AUTO_ROUTING_MODEL_ID = "routing";

export function buildAutoRoutingModelSlotRequest({
  selectedAgent,
  chatId,
}: {
  selectedAgent: string;
  chatId?: string | null;
}): ModelSlotRequest {
  const request: ModelSlotRequest = {
    provider_id: AUTO_ROUTING_PROVIDER_ID,
    model: AUTO_ROUTING_MODEL_ID,
    scope: chatId ? "chat" : "agent",
    agent_id: selectedAgent,
  };
  if (chatId) {
    request.chat_id = chatId;
  }
  return request;
}
