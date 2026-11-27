import { request } from "../request";
import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";

export type AigcCapability =
  | "text_to_image"
  | "image_edit"
  | "image_to_image"
  | "mask_edit"
  | "reference_image"
  | "text_to_video"
  | "image_to_video"
  | "reference_video"
  | "storyboard"
  | string;

export interface AigcCapabilityInfo {
  provider_id: string;
  provider_name: string;
  model_id: string;
  model_name: string;
  capability: AigcCapability;
  source: "model_registry" | "plugin_tool";
  parameter_schema?: Record<string, unknown>;
}

export type AigcModelCategory = "text" | "image" | "video" | "audio";

export interface AigcCapabilityDefaults {
  configured: boolean;
  configured_default: { provider_id: string; model_id: string } | null;
  effective_default: { provider_id: string; model_id: string } | null;
  fallback_active: boolean;
  fallback_reason: string[];
}

export type AigcCapabilityDefaultsByCategory = Partial<
  Record<AigcModelCategory, AigcCapabilityDefaults>
>;

export interface AigcCanvasNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

export interface AigcCanvasEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  data?: Record<string, unknown>;
}

export interface AigcCanvas {
  id: string;
  name: string;
  nodes: AigcCanvasNode[];
  edges: AigcCanvasEdge[];
  viewport: { x: number; y: number; zoom: number };
  thumbnail?: string | null;
  meta?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AigcAsset {
  id: string;
  kind: "image" | "video" | "audio" | "file";
  name: string;
  path: string;
  url?: string | null;
  mime_type?: string | null;
  created_at: string;
  meta?: Record<string, unknown>;
}

export type LongImageExportPayload = {
  canvas_id: string;
  node_id: string;
  width?: number;
  slice_height?: number;
};

export type LongImageExportResult = {
  full_asset: AigcAsset;
  slice_assets: AigcAsset[];
  width: number;
  height: number;
  slice_height: number;
  section_count: number;
};

interface DirectUploadPrepare {
  asset_id: string;
  upload_url: string;
  method?: "PUT";
  headers?: Record<string, string>;
  token: string;
}

export type AigcStyleTemplateType = "style" | "play";
export type AigcStyleTemplateRuntimeMode = "native_effect" | "prompt_style";
export type VisualDnaDimension =
  | "art_direction"
  | "lighting"
  | "camera"
  | "composition"
  | "color"
  | "material"
  | "emotion"
  | "environment"
  | "narrative"
  | "constraint";
export type VisualDnaScope =
  | "aesthetic_profile"
  | "shot"
  | "creation_template"
  | "asset_constraint";

export interface VisualDnaSelection {
  element_id: string;
  weight: number;
  note?: string;
}

export interface VisualDnaElement {
  id: string;
  dimension: VisualDnaDimension;
  name: string;
  aliases: string[];
  definition: string;
  visual_effect: string;
  prompt_text: string;
  tags: string[];
  compatible_with: string[];
  conflicts_with: string[];
  constraints: string[];
  model_overrides: Record<string, string>;
  status: "enabled" | "disabled";
  version: string;
}

export interface VisualDnaDimensionInfo {
  id: VisualDnaDimension;
  name: string;
  description: string;
  scope?: VisualDnaScope;
  element_count: number;
}

export interface CompiledVisualDna {
  selections: VisualDnaSelection[];
  elements: VisualDnaElement[];
  prompt_appendix: string;
  constraints: string[];
  warnings: string[];
}

export interface AigcStyleTemplate {
  id: string;
  title: string;
  type: AigcStyleTemplateType;
  provider: string;
  model_family?: string | null;
  cover_url?: string | null;
  category: string;
  tags: string[];
  keywords: string;
  description: string;
  supplemental_prompt?: string;
  prompt_template?: string;
  visual_dna?: VisualDnaSelection[];
  reference_image_urls?: string[];
  profile_version?: string;
  commercial: boolean;
  runtime_mode: AigcStyleTemplateRuntimeMode;
  effect_template_uuid?: string | null;
  effect_id?: number | null;
  use_count: number;
  favorite?: boolean;
  status: "enabled" | "disabled";
  created_at?: string;
  updated_at?: string;
  last_used_at?: string | null;
}

export type AigcStyleTemplateCreatePayload = {
  id?: string;
  title: string;
  type?: AigcStyleTemplateType;
  provider?: string;
  model_family?: string | null;
  cover_url?: string | null;
  category?: string;
  tags?: string[];
  keywords?: string;
  description?: string;
  supplemental_prompt?: string;
  prompt_template?: string;
  visual_dna?: VisualDnaSelection[];
  reference_image_urls?: string[];
  profile_version?: string;
  commercial?: boolean;
  runtime_mode?: AigcStyleTemplateRuntimeMode;
  effect_template_uuid?: string | null;
  effect_id?: number | null;
  favorite?: boolean;
  status?: "enabled" | "disabled";
};

export type AigcStyleTemplateQuery = {
  type?: AigcStyleTemplateType;
  model_family?: string;
  category?: string;
  q?: string;
  commercial_only?: boolean;
  limit?: number;
  offset?: number;
};

export interface AigcJob {
  id: string;
  canvas_id: string;
  node_id: string;
  capability: string;
  provider_id: string;
  model_id: string;
  inputs: Record<string, unknown>;
  parameters: Record<string, unknown>;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  outputs: AigcAsset[];
  error?: string | null;
  logs: string[];
  created_at: string;
  updated_at: string;
}

export type CanvasPayload = Pick<
  AigcCanvas,
  "name" | "nodes" | "edges" | "viewport" | "thumbnail" | "meta"
>;

const AIGC_JOB_TERMINAL_STATUSES = new Set<AigcJob["status"]>([
  "succeeded",
  "failed",
  "cancelled",
]);
const AIGC_JOB_POLL_INTERVAL_MS = 1500;
const AIGC_JOB_POLL_TIMEOUT_MS = 20 * 60 * 1000;
const AIGC_JOB_RECOVERY_INTERVAL_MS = 30 * 1000;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isTerminalJob(job: AigcJob): boolean {
  return AIGC_JOB_TERMINAL_STATUSES.has(job.status);
}

async function getJob(jobId: string): Promise<AigcJob> {
  return request<AigcJob>(`/aigc-studio/jobs/${encodeURIComponent(jobId)}`);
}

async function pollJobUntilTerminal(startedJob: AigcJob): Promise<AigcJob> {
  if (isTerminalJob(startedJob)) {
    return startedJob;
  }

  const jobId = startedJob.id;
  const deadline = Date.now() + AIGC_JOB_POLL_TIMEOUT_MS;
  let nextRecoveryAt = Date.now() + AIGC_JOB_RECOVERY_INTERVAL_MS;
  let latest = startedJob;

  while (!isTerminalJob(latest)) {
    try {
      if (Date.now() >= nextRecoveryAt) {
        // The provider may complete after the server-side polling window. This
        // endpoint resumes the persisted provider task in query-only mode, so
        // it cannot submit or charge for the generation a second time.
        latest = await request<AigcJob>(
          `/aigc-studio/jobs/${encodeURIComponent(jobId)}/run?background=true`,
          { method: "POST" },
        );
        nextRecoveryAt = Date.now() + AIGC_JOB_RECOVERY_INTERVAL_MS;
      } else {
        latest = await getJob(jobId);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const nonRetryable = /not authenticated|\b40[134]\b/i.test(message);
      if (nonRetryable || Date.now() >= deadline) throw error;
      await wait(AIGC_JOB_POLL_INTERVAL_MS);
      continue;
    }
    if (isTerminalJob(latest)) {
      return latest;
    }
    if (Date.now() >= deadline) {
      throw new Error("AIGC job timed out while waiting for completion.");
    }
    await wait(AIGC_JOB_POLL_INTERVAL_MS);
  }

  return latest;
}

async function uploadAssetViaServer(file: File): Promise<AigcAsset> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(getApiUrl("/aigc-studio/assets/upload"), {
    method: "POST",
    body: form,
    headers: buildAuthHeaders(),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Upload failed: ${response.status}`);
  }
  return response.json() as Promise<AigcAsset>;
}

async function uploadAssetDirectly(file: File): Promise<AigcAsset> {
  const filename = file.name || "asset";
  const mimeType = file.type || "application/octet-stream";
  const prepareResponse = await fetch(
    getApiUrl("/aigc-studio/assets/direct-upload"),
    {
      method: "POST",
      headers: {
        ...buildAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        filename,
        mime_type: mimeType,
        size: file.size,
      }),
    },
  );
  if (!prepareResponse.ok) {
    const text = await prepareResponse.text().catch(() => "");
    throw new Error(
      text || `Direct upload prepare failed: ${prepareResponse.status}`,
    );
  }

  const prepare = (await prepareResponse.json()) as DirectUploadPrepare;
  const putResponse = await fetch(prepare.upload_url, {
    method: prepare.method || "PUT",
    headers: prepare.headers || {},
    body: file,
  });
  if (!putResponse.ok) {
    const text = await putResponse.text().catch(() => "");
    throw new Error(text || `Direct upload failed: ${putResponse.status}`);
  }

  const completeResponse = await fetch(
    getApiUrl("/aigc-studio/assets/direct-upload/complete"),
    {
      method: "POST",
      headers: {
        ...buildAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        asset_id: prepare.asset_id,
        token: prepare.token,
      }),
    },
  );
  if (!completeResponse.ok) {
    const text = await completeResponse.text().catch(() => "");
    throw new Error(
      text || `Direct upload complete failed: ${completeResponse.status}`,
    );
  }

  return completeResponse.json() as Promise<AigcAsset>;
}

export const aigcStudioApi = {
  listCapabilities: () =>
    request<{
      capabilities: AigcCapabilityInfo[];
      defaults: AigcCapabilityDefaultsByCategory;
    }>("/aigc-studio/capabilities"),

  listWorkflowCapabilities: () =>
    request<{ available_models: AigcCapabilityInfo[] }>(
      "/aigc-studio/workflow-capabilities",
    ),

  listVisualDnaDimensions: () =>
    request<{ dimensions: VisualDnaDimensionInfo[] }>(
      "/aigc-studio/visual-dna/dimensions",
    ),

  listVisualDnaElements: (
    params: {
      dimension?: VisualDnaDimension;
      q?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ elements: VisualDnaElement[]; total: number }>(
      `/aigc-studio/visual-dna/elements${suffix}`,
    );
  },

  compileVisualDna: (body: {
    selections: VisualDnaSelection[];
    provider_id?: string;
    model_id?: string;
    constraints?: string[];
  }) =>
    request<CompiledVisualDna>("/aigc-studio/visual-dna/compile", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listStyleTemplates: (params: AigcStyleTemplateQuery = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ templates: AigcStyleTemplate[] }>(
      `/aigc-studio/style-templates${suffix}`,
    );
  },

  markStyleTemplateUsed: (templateId: string) =>
    request<AigcStyleTemplate>(
      `/aigc-studio/style-templates/${encodeURIComponent(templateId)}/use`,
      {
        method: "POST",
      },
    ),

  listFavoriteStyleTemplates: (
    params: Pick<AigcStyleTemplateQuery, "limit" | "offset"> = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ templates: AigcStyleTemplate[] }>(
      `/aigc-studio/style-templates/favorites${suffix}`,
    );
  },

  listRecentStyleTemplates: (
    params: Pick<AigcStyleTemplateQuery, "limit" | "offset"> = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ templates: AigcStyleTemplate[] }>(
      `/aigc-studio/style-templates/recent${suffix}`,
    );
  },

  updateStyleTemplateFavorite: (templateId: string, favorite: boolean) =>
    request<AigcStyleTemplate>(
      `/aigc-studio/style-templates/${encodeURIComponent(templateId)}/favorite`,
      {
        method: "POST",
        body: JSON.stringify({ favorite }),
      },
    ),

  createStyleTemplate: (body: AigcStyleTemplateCreatePayload) =>
    request<AigcStyleTemplate>("/aigc-studio/style-templates", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateStyleTemplate: (
    templateId: string,
    body: AigcStyleTemplateCreatePayload,
  ) =>
    request<AigcStyleTemplate>(
      `/aigc-studio/style-templates/${encodeURIComponent(templateId)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  deleteStyleTemplate: (templateId: string) =>
    request<void>(
      `/aigc-studio/style-templates/${encodeURIComponent(templateId)}`,
      {
        method: "DELETE",
      },
    ),

  listCanvases: () =>
    request<{ canvases: AigcCanvas[] }>("/aigc-studio/canvases"),

  createCanvas: (body: CanvasPayload) =>
    request<AigcCanvas>("/aigc-studio/canvases", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getCanvas: (canvasId: string) =>
    request<AigcCanvas>(
      `/aigc-studio/canvases/${encodeURIComponent(canvasId)}`,
    ),

  saveCanvas: (canvasId: string, body: CanvasPayload) =>
    request<AigcCanvas>(
      `/aigc-studio/canvases/${encodeURIComponent(canvasId)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  deleteCanvas: (canvasId: string) =>
    request<void>(`/aigc-studio/canvases/${encodeURIComponent(canvasId)}`, {
      method: "DELETE",
    }),

  listJobs: (canvasId?: string) =>
    request<{ jobs: AigcJob[] }>(
      canvasId
        ? `/aigc-studio/jobs?canvas_id=${encodeURIComponent(canvasId)}`
        : "/aigc-studio/jobs",
    ),

  submitJob: (body: {
    canvas_id: string;
    node_id: string;
    capability: string;
    provider_id: string;
    model_id: string;
    inputs?: Record<string, unknown>;
    parameters?: Record<string, unknown>;
  }) =>
    request<AigcJob>("/aigc-studio/jobs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  cancelJob: (jobId: string) =>
    request<AigcJob>(`/aigc-studio/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    }),

  retryJob: (jobId: string) =>
    request<AigcJob>(`/aigc-studio/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: "POST",
    }),

  runJob: async (jobId: string) => {
    const started = await request<AigcJob>(
      `/aigc-studio/jobs/${encodeURIComponent(jobId)}/run?background=true`,
      {
        method: "POST",
      },
    );
    return pollJobUntilTerminal(started);
  },

  listAssets: () => request<{ assets: AigcAsset[] }>("/aigc-studio/assets"),

  exportLongImage: (body: LongImageExportPayload) =>
    request<LongImageExportResult>("/aigc-studio/long-image-exports", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  uploadAsset: async (file: File) => {
    try {
      return await uploadAssetDirectly(file);
    } catch (error) {
      console.warn(
        "Direct OSS asset upload failed, falling back to server upload:",
        error,
      );
      return uploadAssetViaServer(file);
    }
  },
};
