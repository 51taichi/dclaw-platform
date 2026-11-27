import { request } from "../request";
import type { ExpertTeamRun, ExpertTeamTemplate } from "../types/expertTeams";

export const expertTeamsApi = {
  listExpertTeams: () => request<ExpertTeamTemplate[]>("/expert-teams"),

  getExpertTeam: (teamId: string) =>
    request<ExpertTeamTemplate>(`/expert-teams/${teamId}`),

  createRun: (
    teamId: string,
    payload: {
      root_chat_id: string;
      root_session_id: string;
      input_text?: string;
    },
  ) =>
    request<ExpertTeamRun>(`/expert-teams/${teamId}/runs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getRun: (runId: string) =>
    request<ExpertTeamRun>(`/expert-team-runs/${runId}`),

  getRunByChat: (chatId: string) =>
    request<ExpertTeamRun | null>(`/expert-team-runs/by-chat/${chatId}`),

  cancelRun: (runId: string) =>
    request<ExpertTeamRun>(`/expert-team-runs/${runId}/cancel`, {
      method: "POST",
    }),

  continueRun: (runId: string) =>
    request<ExpertTeamRun>(`/expert-teams/runs/${runId}/continue`, {
      method: "POST",
    }),

  listAdminExpertTeams: () =>
    request<ExpertTeamTemplate[]>("/admin/expert-teams"),

  createAdminExpertTeam: (payload: Partial<ExpertTeamTemplate>) =>
    request<ExpertTeamTemplate>("/admin/expert-teams", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateAdminExpertTeam: (
    teamId: string,
    payload: Partial<ExpertTeamTemplate>,
  ) =>
    request<ExpertTeamTemplate>(`/admin/expert-teams/${teamId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteAdminExpertTeam: (teamId: string) =>
    request<{ deleted: boolean }>(`/admin/expert-teams/${teamId}`, {
      method: "DELETE",
    }),
};
