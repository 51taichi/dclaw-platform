import { request } from "../request";

export interface AuditChat {
  id: string;
  user_id: string;
  agent_id: string;
  session_id: string;
  channel: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
  meta: any;
}

export interface GetAuditChatsParams {
  user_id?: string;
  agent_id?: string;
  limit?: number;
  offset?: number;
}

export const auditApi = {
  getAuditChats: (params: GetAuditChatsParams) => {
    const search = new URLSearchParams();
    if (params.user_id) search.set("user_id", params.user_id);
    if (params.agent_id) search.set("agent_id", params.agent_id);
    if (params.limit) search.set("limit", params.limit.toString());
    if (params.offset) search.set("offset", params.offset.toString());
    return request<AuditChat[]>(`/admin/audit/chats?${search.toString()}`);
  },

  getAuditChatMessages: (chatId: string) =>
    request<any[]>(`/admin/audit/chats/${chatId}/messages`),
};
