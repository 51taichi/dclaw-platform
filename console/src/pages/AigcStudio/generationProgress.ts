type ImageGenerationProgressInput = {
  providerId?: string | null;
  modelId?: string | null;
  parameters?: Record<string, unknown>;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const numericParameter = (value: unknown) => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const normalizedToken = (value: unknown) => String(value ?? "").toLowerCase();

function baseImageGenerationMs(providerId?: string | null, modelId?: string | null) {
  const provider = normalizedToken(providerId);
  const model = normalizedToken(modelId);
  if (provider.includes("mxapi") || model.includes("gpt-image-2")) {
    return 40_000;
  }
  if (provider.includes("volc") || model.includes("seedream")) {
    return 30_000;
  }
  return 35_000;
}

function resolutionMultiplier(parameters: Record<string, unknown>) {
  const raw = normalizedToken(
    parameters.resolution ?? parameters.imageResolution ?? parameters.clarity,
  );
  if (raw.includes("4")) return 1.35;
  if (raw.includes("3")) return 1.18;
  if (raw.includes("1")) return 0.82;
  return 1;
}

function imageCountMultiplier(parameters: Record<string, unknown>) {
  const count = numericParameter(parameters.imageCount ?? parameters.n) ?? 1;
  return 1 + Math.max(0, Math.min(8, count - 1)) * 0.28;
}

export function estimatedImageGenerationMs({
  providerId,
  modelId,
  parameters = {},
}: ImageGenerationProgressInput) {
  const estimate =
    baseImageGenerationMs(providerId, modelId) *
    resolutionMultiplier(parameters) *
    imageCountMultiplier(parameters);
  return Math.round(clamp(estimate, 12_000, 120_000));
}

export function estimatedImageGenerationSecondsLabel(
  input: ImageGenerationProgressInput,
) {
  return `${Math.max(1, Math.round(estimatedImageGenerationMs(input) / 1000))}s`;
}

export function simulatedImageGenerationProgress(
  elapsedMs: number,
  estimatedMs: number,
) {
  if (!Number.isFinite(elapsedMs) || !Number.isFinite(estimatedMs) || estimatedMs <= 0) {
    return 2;
  }
  const ratio = clamp(elapsedMs / estimatedMs, 0, 1);
  const eased = Math.pow(ratio, 0.86);
  return Math.round(clamp(2 + 96 * eased, 2, 98));
}
