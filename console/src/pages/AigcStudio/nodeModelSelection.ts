import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../api/modules/aigcStudio";

const IMAGE_CAPABILITIES = new Set([
  "text_to_image",
  "image_to_image",
  "image_edit",
  "mask_edit",
  "reference_image",
]);

const VIDEO_GENERATION_CAPABILITIES = new Set([
  "text_to_video",
  "image_to_video",
]);

const CAPABILITY_PRIORITY = [
  "text_to_image",
  "image_to_image",
  "image_edit",
  "mask_edit",
  "reference_image",
  "text_to_video",
  "image_to_video",
  "reference_video",
  "text_to_audio",
  "storyboard",
];

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

export const modelKey = (model?: AigcCapabilityInfo | null) =>
  model ? `${model.provider_id}:${model.model_id}` : "";

export const nodeModelKey = (node: AigcCanvasNode) => {
  const providerId = textValue(node.data.providerId);
  const modelId = textValue(node.data.modelId);
  return providerId && modelId ? `${providerId}:${modelId}` : "";
};

const capabilityRank = (capability: string) => {
  const index = CAPABILITY_PRIORITY.indexOf(capability);
  return index === -1 ? CAPABILITY_PRIORITY.length : index;
};

function uniqueModelOptions(options: AigcCapabilityInfo[]) {
  const uniqueModels = new Map<string, AigcCapabilityInfo>();
  options.forEach((model) => {
    const key = modelKey(model);
    const existing = uniqueModels.get(key);
    if (
      !existing ||
      capabilityRank(model.capability) < capabilityRank(existing.capability)
    ) {
      uniqueModels.set(key, model);
    }
  });
  return Array.from(uniqueModels.values());
}

export function modelOptionsForCapability(
  capabilities: AigcCapabilityInfo[],
  capability: string,
) {
  if (capability === "text_to_image") {
    return uniqueModelOptions(
      capabilities.filter((model) => IMAGE_CAPABILITIES.has(model.capability)),
    );
  }
  if (VIDEO_GENERATION_CAPABILITIES.has(capability)) {
    return uniqueModelOptions(
      capabilities.filter((model) =>
        VIDEO_GENERATION_CAPABILITIES.has(model.capability),
      ),
    );
  }
  if (capability === "reference_video") {
    return uniqueModelOptions(
      capabilities.filter((model) => model.capability === "reference_video"),
    );
  }
  if (capability.includes("audio")) {
    return uniqueModelOptions(
      capabilities.filter((model) => model.capability.includes("audio")),
    );
  }
  return uniqueModelOptions(
    capabilities.filter((model) => model.capability === capability),
  );
}

export function modelSnapshotFromNode(
  node: AigcCanvasNode,
  capability: string,
): AigcCapabilityInfo | null {
  const providerId = textValue(node.data.providerId);
  const modelId = textValue(node.data.modelId);
  if (!providerId || !modelId) return null;
  const modelCapability = textValue(node.data.modelCapability) || capability;
  return {
    provider_id: providerId,
    provider_name: textValue(node.data.providerName) || providerId,
    model_id: modelId,
    model_name: textValue(node.data.modelLabel) || modelId,
    capability: modelCapability,
    source: "model_registry",
  };
}

const canUseNodeSnapshot = (
  snapshot: AigcCapabilityInfo | null,
  options: AigcCapabilityInfo[],
) => {
  if (!snapshot) return false;
  if (!options.length) return true;
  return false;
};

export function modelForNode(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
) {
  const options = modelOptionsForCapability(capabilities, capability);
  const currentKey = nodeModelKey(node);
  const matched = options.find((model) => modelKey(model) === currentKey);
  const snapshot = modelSnapshotFromNode(node, capability);
  if (matched) return matched;
  if (canUseNodeSnapshot(snapshot, options)) return snapshot;
  return options[0] ?? null;
}

export function modelOptionsForNode(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
) {
  const options = modelOptionsForCapability(capabilities, capability);
  const snapshot = modelSnapshotFromNode(node, capability);
  if (
    !snapshot ||
    !canUseNodeSnapshot(snapshot, options) ||
    options.some((model) => modelKey(model) === modelKey(snapshot))
  ) {
    return options;
  }
  return [snapshot, ...options];
}

export function modelLabelForNode(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
  fallback: string,
) {
  const model = modelForNode(capabilities, node, capability);
  return String(
    node.data.modelLabel ?? model?.model_name ?? model?.model_id ?? fallback,
  );
}
