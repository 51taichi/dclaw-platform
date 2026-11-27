import { request } from "../request";
import type {
  CronDispatchTargetsResponse,
  CronJobExecutionRecord,
  CronJobSpecInput,
  CronJobSpecOutput,
  CronJobView,
} from "../types";

function cronBasePath(): string {
  if (
    typeof window !== "undefined" &&
    window.location.pathname.startsWith("/admin")
  ) {
    return "/admin/cron";
  }
  return "/user/cron";
}

export const cronJobApi = {
  listCronJobs: () => request<CronJobSpecOutput[]>(`${cronBasePath()}/jobs`),

  createCronJob: (spec: CronJobSpecInput) =>
    request<CronJobSpecOutput>(`${cronBasePath()}/jobs`, {
      method: "POST",
      body: JSON.stringify(spec),
    }),

  getCronJob: (jobId: string) =>
    request<CronJobView>(`${cronBasePath()}/jobs/${encodeURIComponent(jobId)}`),

  replaceCronJob: (jobId: string, spec: CronJobSpecInput) =>
    request<CronJobSpecOutput>(
      `${cronBasePath()}/jobs/${encodeURIComponent(jobId)}`,
      {
        method: "PUT",
        body: JSON.stringify(spec),
      },
    ),

  deleteCronJob: (jobId: string) =>
    request<void>(`${cronBasePath()}/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    }),

  pauseCronJob: (jobId: string) =>
    request<void>(`${cronBasePath()}/jobs/${encodeURIComponent(jobId)}/pause`, {
      method: "POST",
    }),

  resumeCronJob: (jobId: string) =>
    request<void>(
      `${cronBasePath()}/jobs/${encodeURIComponent(jobId)}/resume`,
      {
        method: "POST",
      },
    ),

  runCronJob: (jobId: string) =>
    request<void>(`${cronBasePath()}/jobs/${encodeURIComponent(jobId)}/run`, {
      method: "POST",
    }),

  triggerCronJob: (jobId: string) =>
    request<void>(`${cronBasePath()}/jobs/${encodeURIComponent(jobId)}/run`, {
      method: "POST",
    }),

  getCronJobState: (jobId: string) =>
    request<unknown>(
      `${cronBasePath()}/jobs/${encodeURIComponent(jobId)}/state`,
    ),

  getCronJobHistory: (jobId: string) =>
    request<CronJobExecutionRecord[]>(
      `${cronBasePath()}/jobs/${encodeURIComponent(jobId)}/history`,
    ),

  listCronDispatchTargets: (params?: {
    channel?: string;
    keyword?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.keyword) searchParams.append("keyword", params.keyword);
    const query = searchParams.toString();
    return request<CronDispatchTargetsResponse>(
      `${cronBasePath()}/dispatch-targets${query ? `?${query}` : ""}`,
    );
  },
};
