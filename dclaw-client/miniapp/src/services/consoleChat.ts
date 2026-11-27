import { request } from "./api";

export interface ChatSpec {
  id: string;
  session_id: string;
  user_id: string;
  channel: string;
  name: string;
  meta: Record<string, unknown>;
}

const DEFAULT_TASK_AGENT_ID = "default";
const DEFAULT_TASK_ACTIVE_MODE = "craft";

function activeModeOrDefault(activeMode?: string): string {
  return activeMode === undefined ? DEFAULT_TASK_ACTIVE_MODE : activeMode;
}

function sessionIdOrChatId(chat: ChatSpec): string {
  return chat.session_id || chat.id;
}

export interface CreateTaskShellInput {
  name: string;
  agentId?: string;
  activeMode?: string;
  expertTeamId?: string;
}

export interface CreateTaskInput extends CreateTaskShellInput {
  prompt: string;
  skillName?: string;
}

export async function createTaskShell(input: CreateTaskShellInput) {
  return request<ChatSpec>("/chats", {
    method: "POST",
    header: input.agentId
      ? {
          "X-Agent-Id": input.agentId,
        }
      : undefined,
    data: {
      name: input.name,
      session_id: "",
      user_id: "default",
      channel: "console",
      meta: {
        mode: "task",
        agent_id: input.agentId || DEFAULT_TASK_AGENT_ID,
        active_mode: activeModeOrDefault(input.activeMode),
        ...(input.expertTeamId ? { expert_team_id: input.expertTeamId } : {}),
      },
    },
  });
}

export async function submitTaskPrompt(
  chat: ChatSpec,
  prompt: string,
  skillName?: string,
  expertTeamId?: string,
) {
  const sessionId = sessionIdOrChatId(chat);
  return sendTaskPrompt({
    chatId: chat.id,
    sessionId,
    userId: chat.user_id,
    agentId:
      typeof chat.meta?.agent_id === "string" ? chat.meta.agent_id : undefined,
    activeMode:
      typeof chat.meta?.active_mode === "string"
        ? chat.meta.active_mode
        : undefined,
    prompt,
    skillName,
    expertTeamId,
  });
}

export interface SendTaskPromptInput {
  chatId: string;
  sessionId: string;
  prompt: string;
  userId?: string;
  agentId?: string;
  activeMode?: string;
  skillName?: string;
  expertTeamId?: string;
}

export async function sendTaskPrompt(input: SendTaskPromptInput) {
  return request<{
    chat_id: string;
    session_id: string;
    status: string;
    expert_team_run_id?: string;
  }>("/console/chat", {
    method: "POST",
    header: input.agentId
      ? {
          "X-Agent-Id": input.agentId,
        }
      : undefined,
    data: {
      input: [
        {
          role: "user",
          content: input.prompt,
        },
      ],
      session_id: input.sessionId,
      chat_id: input.chatId,
      user_id: input.userId,
      channel: "console",
      stream: false,
      ...(input.expertTeamId ? { expert_team_id: input.expertTeamId } : {}),
      meta: {
        chat_id: input.chatId,
        user_id: input.userId,
        agent_id: input.agentId,
        active_mode: activeModeOrDefault(input.activeMode),
        selected_skill: input.skillName,
        ...(input.expertTeamId ? { expert_team_id: input.expertTeamId } : {}),
        mode: "task",
        root_session_id: input.sessionId,
      },
    },
  });
}

export async function createAndSubmitTask(input: CreateTaskInput) {
  const chat = await createTaskShell(input);
  await submitTaskPrompt(
    chat,
    input.prompt,
    input.skillName,
    input.expertTeamId,
  );
  return chat;
}

export function stopTask(chatId: string) {
  return request<{ stopped: boolean }>(
    `/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`,
    {
      method: "POST",
    },
  );
}
