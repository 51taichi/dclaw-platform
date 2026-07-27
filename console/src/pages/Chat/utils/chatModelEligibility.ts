import type { ProviderInfo } from "@/api/types";

const CHAT_UNSUPPORTED_AIGC_CAPABILITIES = new Set([
  "text_to_image",
  "image_to_image",
  "image_edit",
  "mask_edit",
  "text_to_video",
  "image_to_video",
]);

export function isChatSelectableModel(
  model: ProviderInfo["models"][number],
): boolean {
  if (model.model_type && model.model_type !== "llm") return false;
  return !(model.aigc_capabilities ?? []).some((capability) =>
    CHAT_UNSUPPORTED_AIGC_CAPABILITIES.has(capability),
  );
}
