import { requestRoot } from "./api";

export interface MobileModelOption {
  id: string;
  name: string;
  provider?: string;
}

interface ModelInfo {
  id: string;
  name?: string;
  model_type?: "llm" | "image" | "video" | "embedding";
  aigc_capabilities?: string[];
}

interface ProviderInfo {
  id: string;
  name?: string;
  api_key?: string;
  is_local?: boolean;
  disabled?: boolean;
  models?: ModelInfo[];
  extra_models?: ModelInfo[];
}

interface ActiveModelsInfo {
  active_llm?: {
    provider_id: string;
    model: string;
  };
}

interface ModelSelectionInput {
  modelId: string;
  agentId: string;
  chatId?: string;
}

interface ActiveModelInput {
  agentId: string;
  chatId?: string;
}

const CHAT_UNSUPPORTED_AIGC_CAPABILITIES = new Set([
  "text_to_image",
  "image_to_image",
  "image_edit",
  "mask_edit",
  "text_to_video",
  "image_to_video",
]);

const AUTO_ROUTING_PROVIDER_ID = "auto";
const AUTO_ROUTING_MODEL_ID = "routing";

export const AUTO_MODEL_OPTION: MobileModelOption = {
  id: "",
  name: "Auto",
  provider: "智能路由",
};

function isChatSelectableModel(model: ModelInfo): boolean {
  // `/models` is shared with the model-management page and therefore also
  // contains image, video and knowledge-base embedding models. The miniapp
  // selector is a chat LLM selector, so only LLMs belong here. Keep models
  // without this newer field for backward compatibility with older servers.
  if (model.model_type && model.model_type !== "llm") return false;
  return !(model.aigc_capabilities || []).some((capability) =>
    CHAT_UNSUPPORTED_AIGC_CAPABILITIES.has(capability),
  );
}

function buildQuery(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string] => Boolean(entry[1]),
  );
  return entries
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join("&");
}

function parseModelId(modelId: string): { providerId: string; model: string } {
  const separatorIndex = modelId.indexOf("/");
  if (separatorIndex <= 0 || separatorIndex === modelId.length - 1) {
    throw new Error("模型参数无效");
  }
  return {
    providerId: modelId.slice(0, separatorIndex),
    model: modelId.slice(separatorIndex + 1),
  };
}

export async function listModelOptions(): Promise<MobileModelOption[]> {
  const providers = await requestRoot<ProviderInfo[]>("/models");
  const options: MobileModelOption[] = [AUTO_MODEL_OPTION];

  for (const provider of providers) {
    if (provider.disabled) continue;
    if (!provider.api_key && !provider.is_local) continue;
    const models = [...(provider.models || []), ...(provider.extra_models || [])];
    for (const model of models) {
      if (!isChatSelectableModel(model)) continue;
      options.push({
        id: `${provider.id}/${model.id}`,
        name: model.name || model.id,
        provider: provider.name || provider.id,
      });
    }
  }

  return options;
}

export async function getActiveModelId({
  agentId,
  chatId,
}: ActiveModelInput): Promise<string> {
  const query = buildQuery({
    scope: chatId ? "chat" : "effective",
    agent_id: agentId,
    chat_id: chatId,
  });
  const active = await requestRoot<ActiveModelsInfo>(`/models/active?${query}`);
  const slot = active.active_llm;
  if (!slot) {
    return AUTO_MODEL_OPTION.id;
  }
  if (
    slot.provider_id === AUTO_ROUTING_PROVIDER_ID &&
    slot.model === AUTO_ROUTING_MODEL_ID
  ) {
    return AUTO_MODEL_OPTION.id;
  }
  return `${slot.provider_id}/${slot.model}`;
}

export async function setActiveModel({
  modelId,
  agentId,
  chatId,
}: ModelSelectionInput): Promise<ActiveModelsInfo> {
  const scope = chatId ? "chat" : "agent";
  const slot = modelId
    ? parseModelId(modelId)
    : {
        providerId: AUTO_ROUTING_PROVIDER_ID,
        model: AUTO_ROUTING_MODEL_ID,
      };

  return requestRoot<ActiveModelsInfo>("/models/active", {
    method: "PUT",
    data: {
      provider_id: slot.providerId,
      model: slot.model,
      scope,
      agent_id: agentId,
      ...(chatId ? { chat_id: chatId } : {}),
    },
  });
}

export function getModelSelectionUnavailableMessage(
  options: MobileModelOption[],
): string {
  if (options.length === 0) {
    return "暂无可选模型";
  }
  return options.every((option) => option.id === AUTO_MODEL_OPTION.id)
    ? "当前仅支持 Auto"
    : "";
}
