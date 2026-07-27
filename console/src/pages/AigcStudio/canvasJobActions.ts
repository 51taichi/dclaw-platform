import type {
  AigcCanvas,
  AigcCanvasNode,
  AigcCapabilityInfo,
  AigcJob,
} from "../../api/modules/aigcStudio";
import {
  imageGenerationParametersForProfile,
  imageModelParameterProfileFor,
} from "./components/ImageNode/imageModelParameterProfile";
import { parseStoryboardScriptOutput } from "./components/ScriptNode/storyboardParser";
import {
  annotationInputFromNode,
  isImageAnnotationNode,
  isStyleTemplateNode,
  pickNodeData,
  referenceInputFromNode,
} from "./canvasNodeUtils";

type SubmitJobRequest = {
  canvas_id: string;
  node_id: string;
  capability: string;
  provider_id: string;
  model_id: string;
  inputs: Record<string, unknown>;
  parameters: Record<string, unknown>;
};

export type ImageReferenceAsset = {
  id: string;
  alias: string;
  name: string;
  previewUrl: string;
  sourceNodeId?: string;
  kind?: "image" | "text";
  text?: string;
};

export function referenceNodesForRun(
  canvas: AigcCanvas,
  selectedNode: AigcCanvasNode,
) {
  return upstreamNodesForRun(canvas, selectedNode).filter(
    (node) => !isStyleTemplateNode(node),
  );
}

export function styleTemplateNodesForRun(
  canvas: AigcCanvas,
  selectedNode: AigcCanvasNode,
) {
  return upstreamNodesForRun(canvas, selectedNode).filter(isStyleTemplateNode);
}

function upstreamNodesForRun(canvas: AigcCanvas, selectedNode: AigcCanvasNode) {
  return canvas.edges
    .filter((edge) => edge.target === selectedNode.id)
    .map((edge) => canvas.nodes.find((node) => node.id === edge.source))
    .filter(
      (node): node is AigcCanvasNode =>
        Boolean(node) &&
        node?.type !== "reference_note" &&
        node?.data.participatesInGeneration !== false,
    );
}

function mediaKindForVideoInput(node: AigcCanvasNode) {
  const assetKind = textValue(node.data.assetKind);
  if (assetKind === "image" || assetKind === "video" || assetKind === "audio") {
    return assetKind;
  }
  if (node.type === "image_generate" || isImageAnnotationNode(node)) {
    return "image";
  }
  if (node.type === "video_generate") return "video";
  if (node.type === "audio_generate") return "audio";
  if (node.type === "reference_asset") return "image";
  return null;
}

export function videoConnectedInputsForNode(
  canvas: AigcCanvas,
  selectedNode: AigcCanvasNode,
) {
  const summary = {
    imageCount: 0,
    videoCount: 0,
    audioCount: 0,
    totalCount: 0,
  };

  upstreamNodesForRun(canvas, selectedNode).forEach((node) => {
    const kind = mediaKindForVideoInput(node);
    if (!kind) return;
    if (kind === "image") summary.imageCount += 1;
    if (kind === "video") summary.videoCount += 1;
    if (kind === "audio") summary.audioCount += 1;
    summary.totalCount += 1;
  });

  return summary;
}

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function appendUnique<T>(items: T[], value: unknown) {
  if (Array.isArray(value)) {
    value.forEach((item) => appendUnique(items, item));
    return;
  }
  if (value === undefined || value === null || value === "") return;
  if (!items.includes(value as T)) items.push(value as T);
}

const CHINESE_REFERENCE_ORDINALS = [
  "第一",
  "第二",
  "第三",
  "第四",
  "第五",
  "第六",
  "第七",
  "第八",
  "第九",
  "第十",
  "第十一",
  "第十二",
  "第十三",
  "第十四",
  "第十五",
  "第十六",
];

const referencePhraseForIndex = (index: number) =>
  `${CHINESE_REFERENCE_ORDINALS[index] ?? `第${index + 1}`}张参考图`;

const textReferencePhraseForIndex = (
  index: number,
  reference: ImageReferenceAsset,
) => {
  const prefix = `${
    CHINESE_REFERENCE_ORDINALS[index] ?? `第${index + 1}`
  }段参考文本`;
  const text = textValue(reference.text);
  return text ? `${prefix}：${text}` : prefix;
};

const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function replaceReferenceAliasesInPrompt(
  prompt: string,
  references: ImageReferenceAsset[],
) {
  let imageIndex = 0;
  let textIndex = 0;
  return references.reduce((result, reference) => {
    const alias = textValue(reference.alias);
    if (!alias) return result;
    const kind = reference.kind ?? "image";
    const replacement =
      kind === "text"
        ? textReferencePhraseForIndex(textIndex++, reference)
        : referencePhraseForIndex(imageIndex++);
    return result.replace(
      new RegExp(`@${escapeRegExp(alias)}\\b`, "g"),
      replacement,
    );
  }, prompt);
}

function textContentFromNode(node: AigcCanvasNode) {
  return textValue(node.data.text) || textValue(node.data.composerText);
}

function referenceAssetFromNode(
  node: AigcCanvasNode,
): Omit<ImageReferenceAsset, "alias"> | null {
  const input = referenceInputFromNode(node);
  const previewUrl = textValue(input.preview_url);
  const kind = node.type === "prompt" ? "text" : "image";
  if (kind === "image" && !previewUrl) return null;
  return {
    id: textValue(node.data.assetId) || node.id,
    name: textValue(input.asset_name) || textValue(input.title) || "参考素材",
    previewUrl,
    sourceNodeId: node.id,
    kind,
    ...(kind === "text" ? { text: textContentFromNode(node) } : {}),
  };
}

function isPromptReferenceRecord(data: Record<string, unknown>) {
  const kind = textValue(data.kind ?? data.assetKind ?? data.type);
  const previewUrl = textValue(
    data.previewUrl ?? data.url ?? data.assetPreviewUrl,
  ).toLowerCase();
  const recordId = textValue(data.sourceNodeId ?? data.id).toLowerCase();
  return (
    kind === "text" ||
    kind === "prompt" ||
    previewUrl === "prompt" ||
    recordId.startsWith("prompt-")
  );
}

function referenceKindFromRecord(data: Record<string, unknown>) {
  return isPromptReferenceRecord(data) ? "text" : "image";
}

function referenceAssetFromRecord(
  record: unknown,
): Omit<ImageReferenceAsset, "alias"> | null {
  if (!record || typeof record !== "object") return null;
  const data = record as Record<string, unknown>;
  const kind = referenceKindFromRecord(data);
  const previewUrl = textValue(
    data.previewUrl ?? data.url ?? data.assetPreviewUrl,
  );
  if (kind === "image" && !previewUrl) return null;
  return {
    id:
      textValue(data.id) ||
      textValue(data.assetId) ||
      textValue(data.sourceNodeId) ||
      previewUrl ||
      kind,
    name: textValue(data.name ?? data.assetName ?? data.title) || "参考素材",
    previewUrl,
    sourceNodeId: textValue(data.sourceNodeId) || undefined,
    kind,
    ...(kind === "text" ? { text: textValue(data.text) } : {}),
  };
}

function singleReferenceAssetFromNode(
  node: AigcCanvasNode,
): Omit<ImageReferenceAsset, "alias"> | null {
  const previewUrl = textValue(node.data.referencePreviewUrl);
  if (!previewUrl) return null;
  return {
    id: textValue(node.data.referenceAssetId) || previewUrl,
    name: textValue(node.data.referenceAssetName) || "参考素材",
    previewUrl,
    kind: "image",
  };
}

function pushReferenceAsset(
  items: Array<Omit<ImageReferenceAsset, "alias">>,
  item: Omit<ImageReferenceAsset, "alias"> | null,
) {
  if (!item) return;
  const itemKey =
    item.previewUrl ||
    `${item.kind ?? "image"}:${item.sourceNodeId ?? item.id}`;
  if (
    items.some(
      (existing) =>
        (existing.previewUrl ||
          `${existing.kind ?? "image"}:${
            existing.sourceNodeId ?? existing.id
          }`) === itemKey,
    )
  ) {
    return;
  }
  items.push(item);
}

function connectedSourceIdsForNode(
  canvas: AigcCanvas,
  selectedNode: AigcCanvasNode,
) {
  return new Set(
    canvas.edges
      .filter((edge) => edge.target === selectedNode.id)
      .map((edge) => edge.source),
  );
}

function hasValidReferenceRecordSource(
  record: unknown,
  connectedSourceIds: Set<string>,
) {
  if (!record || typeof record !== "object") return false;
  const data = record as Record<string, unknown>;
  const sourceNodeId = textValue(data.sourceNodeId);
  return !sourceNodeId || connectedSourceIds.has(sourceNodeId);
}

export function imageReferenceAssetsForNode(
  canvas: AigcCanvas,
  selectedNode: AigcCanvasNode,
): ImageReferenceAsset[] {
  const items: Array<Omit<ImageReferenceAsset, "alias">> = [];
  const connectedSourceIds = connectedSourceIdsForNode(canvas, selectedNode);

  referenceNodesForRun(canvas, selectedNode).forEach((node) => {
    pushReferenceAsset(items, referenceAssetFromNode(node));
  });
  if (items.length === 0) {
    pushReferenceAsset(items, singleReferenceAssetFromNode(selectedNode));
  }
  if (Array.isArray(selectedNode.data.referencedAssets)) {
    selectedNode.data.referencedAssets.forEach((record) => {
      if (!hasValidReferenceRecordSource(record, connectedSourceIds)) return;
      pushReferenceAsset(items, referenceAssetFromRecord(record));
    });
  }

  let imageIndex = 0;
  let textIndex = 0;
  return items.map((item) => {
    const kind = item.kind ?? "image";
    const alias =
      kind === "text" ? `文本${++textIndex}` : `图片${++imageIndex}`;
    return {
      ...item,
      alias,
    };
  });
}

function schemaNumber(model: AigcCapabilityInfo, keys: string[]) {
  const schema = model.parameter_schema ?? {};
  for (const key of keys) {
    const value = numberValue(schema[key]);
    if (value && value > 0) return value;
  }

  const properties =
    schema.properties && typeof schema.properties === "object"
      ? (schema.properties as Record<string, unknown>)
      : {};
  const referenceImages = properties.referenceImages;
  if (referenceImages && typeof referenceImages === "object") {
    const maxItems = numberValue(
      (referenceImages as Record<string, unknown>).maxItems,
    );
    if (maxItems && maxItems > 0) return maxItems;
  }
  return null;
}

function modelSupportsVideoAudio(model: AigcCapabilityInfo) {
  const schema = model.parameter_schema ?? {};
  const properties =
    schema.properties && typeof schema.properties === "object"
      ? (schema.properties as Record<string, unknown>)
      : {};
  return ["generate_audio", "videoAudio"].some((key) =>
    Object.prototype.hasOwnProperty.call(properties, key),
  );
}

export function referenceImageLimitForModel(model: AigcCapabilityInfo) {
  const configured = schemaNumber(model, [
    "max_reference_images",
    "maxReferenceImages",
    "referenceImageLimit",
  ]);
  if (configured) return configured;

  const token = `${model.provider_id} ${model.model_id} ${model.model_name}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ");
  if (token.includes("gpt image") && token.includes("2")) return 16;
  if (token.includes("nano2") || token.includes("banana2")) return 16;
  if (token.includes("seedream") && token.includes("4 5")) return 10;
  return 4;
}

function referenceImageParameters(
  canvas: AigcCanvas,
  selectedNode: AigcCanvasNode,
  selectedModel: AigcCapabilityInfo,
) {
  const limit = referenceImageLimitForModel(selectedModel);
  const promptReferences = imageReferenceAssetsForNode(canvas, selectedNode);
  const references = promptReferences
    .filter(
      (reference) =>
        (reference.kind ?? "image") !== "text" &&
        Boolean(textValue(reference.previewUrl)),
    )
    .slice(0, limit);
  if (!references.length) {
    return { promptReferences, parameters: {} };
  }
  return {
    promptReferences,
    parameters: {
      referenceImages: references.map((reference) => reference.previewUrl),
      referenceImageAliases: references.map((reference) => ({
        alias: reference.alias,
        name: reference.name,
        previewUrl: reference.previewUrl,
        sourceNodeId: reference.sourceNodeId,
      })),
      referenceImageLimit: limit,
    },
  };
}

function styleTemplateParametersForRun(
  selectedNode: AigcCanvasNode,
  styleNodes: AigcCanvasNode[],
) {
  const effectTemplateUuids: string[] = [];
  const effects: Array<string | number> = [];

  appendUnique(effectTemplateUuids, selectedNode.data.effectTemplateUuids);
  appendUnique(effectTemplateUuids, selectedNode.data.styleTemplateUuid);
  appendUnique(effectTemplateUuids, selectedNode.data.effectTemplateUuid);
  appendUnique(effects, selectedNode.data.effects);
  appendUnique(effects, selectedNode.data.effectId);

  styleNodes.forEach((node) => {
    appendUnique(effectTemplateUuids, node.data.effectTemplateUuids);
    appendUnique(effectTemplateUuids, node.data.styleTemplateUuid);
    appendUnique(effectTemplateUuids, node.data.effectTemplateUuid);
    appendUnique(effects, node.data.effects);
    appendUnique(effects, node.data.effectId);
  });

  const primaryStyleNode = styleNodes[0];
  const styleReferenceName =
    textValue(selectedNode.data.styleReferenceName) ||
    textValue(primaryStyleNode?.data.assetName) ||
    textValue(primaryStyleNode?.data.title);
  const styleReferencePreviewUrl =
    textValue(selectedNode.data.styleReferencePreviewUrl) ||
    textValue(primaryStyleNode?.data.assetPreviewUrl);
  const styleTemplateId =
    textValue(selectedNode.data.styleTemplateId) ||
    textValue(primaryStyleNode?.data.styleTemplateId);
  const styleRuntimeMode =
    textValue(selectedNode.data.styleRuntimeMode) ||
    textValue(primaryStyleNode?.data.styleRuntimeMode);
  const styleKeywords =
    textValue(selectedNode.data.styleKeywords) ||
    textValue(primaryStyleNode?.data.styleKeywords);
  const styleDescription =
    textValue(selectedNode.data.styleDescription) ||
    textValue(primaryStyleNode?.data.styleDescription);
  const styleSupplementalPrompt =
    textValue(selectedNode.data.styleSupplementalPrompt) ||
    textValue(primaryStyleNode?.data.styleSupplementalPrompt);
  const visualDna = Array.isArray(selectedNode.data.visualDna)
    ? selectedNode.data.visualDna
    : Array.isArray(primaryStyleNode?.data.visualDna)
    ? primaryStyleNode.data.visualDna
    : undefined;
  const styleReferenceImages = Array.isArray(
    selectedNode.data.styleReferenceImages,
  )
    ? selectedNode.data.styleReferenceImages
    : Array.isArray(primaryStyleNode?.data.styleReferenceImages)
    ? primaryStyleNode.data.styleReferenceImages
    : undefined;
  const aestheticProfileSnapshot =
    selectedNode.data.aestheticProfileSnapshot &&
    typeof selectedNode.data.aestheticProfileSnapshot === "object"
      ? selectedNode.data.aestheticProfileSnapshot
      : primaryStyleNode?.data.aestheticProfileSnapshot;

  return pickNodeData(
    {
      styleReferenceName,
      styleReferencePreviewUrl,
      styleTemplateId,
      styleRuntimeMode,
      styleKeywords,
      styleDescription,
      styleSupplementalPrompt,
      visualDna,
      styleReferenceImages,
      aestheticProfileSnapshot,
      effectTemplateUuids:
        effectTemplateUuids.length > 0 ? effectTemplateUuids : undefined,
      effects: effects.length > 0 ? effects : undefined,
    },
    [
      "styleReferenceName",
      "styleReferencePreviewUrl",
      "styleTemplateId",
      "styleRuntimeMode",
      "styleKeywords",
      "styleDescription",
      "styleSupplementalPrompt",
      "visualDna",
      "styleReferenceImages",
      "aestheticProfileSnapshot",
      "effectTemplateUuids",
      "effects",
    ],
  );
}

function promptForRun(
  selectedNode: AigcCanvasNode,
  referenceNodes: AigcCanvasNode[],
) {
  if (selectedNode.type === "script_generate") {
    return scriptPromptForRun(selectedNode, referenceNodes);
  }
  const ownPrompt =
    textValue(selectedNode.data.composerText) ||
    textValue(selectedNode.data.text);
  const upstreamPrompt = textValue(
    referenceNodes.find(
      (node) => node.type === "prompt" && textValue(node.data.text),
    )?.data.text,
  );
  return ownPrompt || upstreamPrompt;
}

function scriptPromptForRun(
  selectedNode: AigcCanvasNode,
  referenceNodes: AigcCanvasNode[],
) {
  const instruction =
    textValue(selectedNode.data.composerText) ||
    textValue(selectedNode.data.scriptPrompt) ||
    textValue(selectedNode.data.text);
  const upstreamPrompt = textValue(
    referenceNodes.find(
      (node) => node.type === "prompt" && textValue(node.data.text),
    )?.data.text,
  );
  if (instruction && upstreamPrompt) {
    return `${instruction}\n\n素材/剧本：\n${upstreamPrompt}`;
  }
  return instruction || upstreamPrompt;
}

function capabilityParametersForNode(
  selectedNode: AigcCanvasNode,
  selectedModel: AigcCapabilityInfo,
) {
  if (selectedNode.type === "image_generate") {
    return imageGenerationParametersForProfile(
      imageModelParameterProfileFor(selectedModel),
      selectedNode.data,
    );
  }
  if (selectedNode.type === "video_generate") {
    const parameters = pickNodeData(selectedNode.data, [
      "videoMode",
      "activeVideoTab",
      "videoModel",
      "aspectRatio",
      "videoResolution",
      "videoDuration",
      "videoAudio",
      "videoCount",
      "motionPreset",
      "referenceCount",
      "videoReferenceAssets",
      "returnLastFrame",
      "return_last_frame",
    ]);
    if (!modelSupportsVideoAudio(selectedModel)) delete parameters.videoAudio;
    return parameters;
  }
  if (selectedNode.type === "prompt") {
    return pickNodeData(selectedNode.data, [
      "textMode",
      "blockStyle",
      "bold",
      "italic",
      "listStyle",
    ]);
  }
  if (selectedNode.type === "script_generate") {
    return {
      ...pickNodeData(selectedNode.data, ["scriptInputKind"]),
      textMode: "storyboard_script",
      outputFormat: "storyboard_shots_json",
    };
  }
  if (selectedNode.type === "audio_generate") {
    return pickNodeData(selectedNode.data, [
      "audioMode",
      "audioVoiceId",
      "audioVoiceName",
      "audioPauseTag",
      "audioFillerTag",
      "soundEffect",
      "speechRate",
      "audioDuration",
      "audioCount",
    ]);
  }
  return {};
}

export function buildRunNodeJobRequest({
  canvas,
  selectedNode,
  selectedCapability,
  selectedModel,
}: {
  canvas: AigcCanvas;
  selectedNode: AigcCanvasNode;
  selectedCapability: string;
  selectedModel: AigcCapabilityInfo;
}):
  | { ok: true; request: SubmitJobRequest }
  | { ok: false; reason: "missing_reference" } {
  const referenceNodes = referenceNodesForRun(canvas, selectedNode);
  const styleTemplateNodes = styleTemplateNodesForRun(canvas, selectedNode);
  const annotationNodes = referenceNodes.filter(isImageAnnotationNode);
  const imageReferences = referenceImageParameters(
    canvas,
    selectedNode,
    selectedModel,
  );
  const styleParameters = styleTemplateParametersForRun(
    selectedNode,
    styleTemplateNodes,
  );
  const regularReferenceCount = Array.isArray(
    imageReferences.parameters.referenceImages,
  )
    ? imageReferences.parameters.referenceImages.length
    : 0;
  const remainingStyleReferenceSlots = Math.max(
    0,
    referenceImageLimitForModel(selectedModel) - regularReferenceCount,
  );
  if (Array.isArray(styleParameters.styleReferenceImages)) {
    styleParameters.styleReferenceImages = styleParameters.styleReferenceImages
      .filter((value): value is string => Boolean(textValue(value)))
      .slice(0, remainingStyleReferenceSlots);
  }
  const hasReferenceInput =
    referenceNodes.length > 0 ||
    imageReferences.promptReferences.length > 0 ||
    Boolean(
      selectedNode.data.referenceAssetName ||
        selectedNode.data.referencePreviewUrl ||
        selectedNode.data.referenceThumb,
    );
  if (
    selectedNode.type === "image_generate" &&
    selectedNode.data.slashCommand &&
    !hasReferenceInput
  ) {
    return { ok: false, reason: "missing_reference" };
  }

  const baseParameters = pickNodeData(selectedNode.data, [
    "modelLabel",
    "providerId",
    "modelId",
    "referenceAssetName",
    "referencePreviewUrl",
    "annotationAssetName",
    "annotationPreviewUrl",
    "annotationSourcePreviewUrl",
    "annotationInstruction",
    "annotationMode",
    "imageEditScope",
    "lastRunPrompt",
  ]);

  return {
    ok: true,
    request: {
      canvas_id: canvas.id,
      node_id: selectedNode.id,
      capability: selectedModel.capability || selectedCapability,
      provider_id: selectedModel.provider_id,
      model_id: selectedModel.model_id,
      inputs: {
        prompt: replaceReferenceAliasesInPrompt(
          promptForRun(selectedNode, referenceNodes),
          imageReferences.promptReferences,
        ),
        node_type: selectedNode.type,
        reference_nodes: referenceNodes.map(referenceInputFromNode),
        ...(annotationNodes.length > 0
          ? { annotations: annotationNodes.map(annotationInputFromNode) }
          : {}),
      },
      parameters: {
        ...baseParameters,
        ...capabilityParametersForNode(selectedNode, selectedModel),
        ...imageReferences.parameters,
        ...styleParameters,
      },
    },
  };
}

export function prependCanvasJob(jobs: AigcJob[], job: AigcJob) {
  return [job, ...jobs];
}

export function replaceCanvasJob(jobs: AigcJob[], job: AigcJob) {
  return jobs.map((item) => (item.id === job.id ? job : item));
}

function outputTextFromJob(job: AigcJob) {
  for (const output of job.outputs) {
    const text = textValue(output.meta?.text);
    if (text) return text;
  }
  return "";
}

function generationStateFromJob(job: AigcJob) {
  return job.status === "succeeded"
    ? "generated"
    : job.status === "failed" || job.status === "cancelled"
    ? "failed"
    : "generating";
}

function scriptNodePatchFromFinishedJob(job: AigcJob) {
  const rawOutput = outputTextFromJob(job);
  if (job.status !== "succeeded") {
    return {
      scriptMode: "idle",
      scriptProgress: null,
      scriptParseStatus: null,
      scriptParseError: null,
      scriptRawOutput: rawOutput || null,
      job_error: job.error ?? null,
    };
  }

  const parsed = parseStoryboardScriptOutput(rawOutput);
  if (!parsed.ok) {
    return {
      scriptMode: "script_ready",
      scriptProgress: 100,
      scriptParseStatus: "failed",
      scriptParseError: parsed.error,
      scriptRawOutput: parsed.rawText,
      scriptShots: [],
      selectedShotIds: [],
      scriptWorkflowStep: "shots",
      job_error: job.error ?? null,
    };
  }

  return {
    scriptMode: "script_ready",
    scriptProgress: 100,
    scriptParseStatus: "ready",
    scriptParseError: null,
    scriptRawOutput: parsed.rawText,
    scriptTitle: parsed.title,
    scriptShots: parsed.shots,
    selectedShotIds: parsed.shots.map((shot) => shot.id),
    scriptWorkflowStep: "shots",
    job_error: job.error ?? null,
  };
}

export function applyFinishedJobToCanvas({
  canvas,
  nodeId,
  job,
}: {
  canvas: AigcCanvas;
  nodeId: string;
  job: AigcJob;
}): AigcCanvas {
  const jobState = generationStateFromJob(job);
  const finishedNode = canvas.nodes.find((node) => node.id === nodeId);
  const sourceScriptNodeId = textValue(finishedNode?.data.sourceScriptNodeId);
  const scriptAssetId = textValue(finishedNode?.data.scriptAssetId);
  const scriptAssetStatus =
    sourceScriptNodeId && scriptAssetId
      ? job.status === "succeeded"
        ? "ready"
        : job.status === "failed" || job.status === "cancelled"
        ? "idle"
        : null
      : null;

  return {
    ...canvas,
    nodes: canvas.nodes.map((node) => {
      if (node.id === nodeId) {
        return {
          ...node,
          data: {
            ...node.data,
            job_id: job.id,
            job_status: job.status,
            ...(node.type === "image_generate"
              ? {
                  imageState: jobState,
                  imageProgress: null,
                  job_error: job.error ?? null,
                  primaryOutputId:
                    job.status === "succeeded" && job.outputs.length > 0
                      ? job.outputs[0]?.id ?? null
                      : node.data.primaryOutputId,
                  primaryOutputIndex:
                    job.status === "succeeded" && job.outputs.length > 0
                      ? null
                      : node.data.primaryOutputIndex,
                  imageResultsExpanded:
                    job.status === "succeeded"
                      ? false
                      : node.data.imageResultsExpanded,
                  generatedAspectRatio:
                    job.status === "succeeded"
                      ? job.parameters.aspectRatio
                      : node.data.generatedAspectRatio,
                }
              : {}),
            ...(node.type === "prompt"
              ? {
                  textState: jobState,
                  job_error: job.error ?? null,
                  ...(job.status === "succeeded" && outputTextFromJob(job)
                    ? {
                        text: outputTextFromJob(job),
                        textMode:
                          String(node.data.textMode ?? "") || "generated",
                        showTryOptions: false,
                      }
                    : {}),
                }
              : {}),
            ...(node.type === "script_generate"
              ? scriptNodePatchFromFinishedJob(job)
              : {}),
            ...(node.type === "video_generate"
              ? {
                  videoState: jobState,
                  videoProgress: null,
                  job_error: job.error ?? null,
                  generatedAspectRatio:
                    job.status === "succeeded"
                      ? job.parameters.aspectRatio
                      : node.data.generatedAspectRatio,
                }
              : {}),
            ...(node.type === "audio_generate"
              ? {
                  audioState: jobState,
                  audioProgress: null,
                  job_error: job.error ?? null,
                }
              : {}),
            outputs: job.outputs,
          },
        };
      }
      if (
        scriptAssetStatus &&
        sourceScriptNodeId &&
        scriptAssetId &&
        node.id === sourceScriptNodeId &&
        node.type === "script_generate"
      ) {
        const scriptAssetStates =
          node.data.scriptAssetStates &&
          typeof node.data.scriptAssetStates === "object" &&
          !Array.isArray(node.data.scriptAssetStates)
            ? (node.data.scriptAssetStates as Record<string, unknown>)
            : {};
        return {
          ...node,
          data: {
            ...node.data,
            scriptAssetStates: {
              ...scriptAssetStates,
              [scriptAssetId]: scriptAssetStatus,
            },
            scriptAssetProgress: null,
          },
        };
      }
      return node;
    }),
  };
}
