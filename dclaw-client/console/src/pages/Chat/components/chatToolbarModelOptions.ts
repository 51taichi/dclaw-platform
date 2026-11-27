import type { ProviderInfo } from "@/api/types";
import { isChatSelectableModel } from "../utils/chatModelEligibility";

export interface ChatToolbarModelOption {
  id: string;
  name: string;
  provider?: string;
}

export function buildChatToolbarModelOptions(
  providers: ProviderInfo[],
): ChatToolbarModelOption[] {
  const models: ChatToolbarModelOption[] = [];

  for (const provider of providers) {
    if (provider.disabled) continue;
    const hasKey = Boolean(provider.api_key);
    const isLocal = Boolean(provider.is_local);
    if (!hasKey && !isLocal) continue;

    const allModels = [
      ...(provider.models || []),
      ...(provider.extra_models || []),
    ];
    for (const model of allModels) {
      if (!isChatSelectableModel(model)) continue;
      models.push({
        id: `${provider.id}/${model.id}`,
        name: model.name || model.id,
        provider: provider.name,
      });
    }
  }

  return models;
}
