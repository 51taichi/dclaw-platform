import type {
  AigcCanvasNode,
  AigcCapabilityDefaultsByCategory,
  AigcCapabilityInfo,
  AigcModelCategory,
} from "../../api/modules/aigcStudio";

export type AigcModelRef = { provider_id: string; model_id: string };

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

export function categoryForCapability(capability: string): AigcModelCategory {
  if (IMAGE_CAPABILITIES.has(capability)) return "image";
  if (
    VIDEO_GENERATION_CAPABILITIES.has(capability) ||
    capability === "reference_video"
  ) {
    return "video";
  }
  if (capability.includes("audio")) return "audio";
  return "text";
}

export function effectiveDefaultForCapability(
  defaults: AigcCapabilityDefaultsByCategory,
  capability: string,
) {
  return defaults[categoryForCapability(capability)]?.effective_default ?? null;
}

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

export function modelForNewNode(
  options: AigcCapabilityInfo[],
  effectiveDefault?: AigcModelRef | null,
) {
  if (effectiveDefault) {
    const preferred = options.find(
      (model) =>
        model.provider_id === effectiveDefault.provider_id &&
        model.model_id === effectiveDefault.model_id,
    );
    if (preferred) return preferred;
  }
  return options[0] ?? null;
}

export function modelSelectionState(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
  effectiveDefault?: AigcModelRef | null,
) {
  const categoryOptions = modelOptionsForCapability(capabilities, capability);
  const snapshot = modelSnapshotFromNode(node, capability);
  const currentKey = nodeModelKey(node);
  const boundCapability = textValue(node.data.modelCapability);
  const workflowBound = Boolean(textValue(node.data.workflowLogicalNodeId));
  const options = workflowBound
    ? uniqueModelOptions(
        capabilities.filter((model) => model.capability === capability),
      )
    : categoryOptions;
  const matched = options.find(
    (model) =>
      modelKey(model) === currentKey &&
      (!boundCapability || model.capability === boundCapability),
  );
  const fallback = modelForNewNode(options, effectiveDefault);
  const invalidSavedModel = Boolean(snapshot && !matched && !workflowBound);
  return {
    selected: matched ?? fallback ?? (invalidSavedModel ? snapshot : null),
    fallback,
    invalidSavedModel,
  };
}

export function modelForNode(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
  effectiveDefault?: AigcModelRef | null,
) {
  return modelSelectionState(capabilities, node, capability, effectiveDefault)
    .selected;
}

export function modelOptionsForNode(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
) {
  const categoryOptions = modelOptionsForCapability(capabilities, capability);
  const workflowBound = Boolean(textValue(node.data.workflowLogicalNodeId));
  if (workflowBound) {
    return uniqueModelOptions(
      capabilities.filter((model) => model.capability === capability),
    );
  }
  return categoryOptions;
}

export function modelLabelForNode(
  capabilities: AigcCapabilityInfo[],
  node: AigcCanvasNode,
  capability: string,
  fallback: string,
  effectiveDefault?: AigcModelRef | null,
) {
  const selection = modelSelectionState(
    capabilities,
    node,
    capability,
    effectiveDefault,
  );
  const model = selection.selected;
  return String(
    selection.invalidSavedModel
      ? model?.model_name ?? model?.model_id ?? fallback
      : node.data.modelLabel ??
          model?.model_name ??
          model?.model_id ??
          fallback,
  );
}
