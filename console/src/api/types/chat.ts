export type ChatStatus = "idle" | "running";

export interface ChatSpec {
  id: string; // Chat UUID identifier
  session_id: string; // Session identifier (channel:user_id format)
  user_id: string; // User identifier
  channel: string; // Channel name, default: "default"
  name?: string; // Chat display name
  created_at: string | null; // Chat creation timestamp (ISO 8601)
  updated_at: string | null; // Chat last update timestamp (ISO 8601)
  meta?: Record<string, unknown>; // Additional metadata
  status?: ChatStatus; // Conversation status: idle or running
  task_status?: string; // Business status: pending, in_progress, completed, failed, planning
  pinned?: boolean; // Whether the chat is pinned to the top
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  status?: ChatStatus; // Conversation status: idle or running
}

export interface ChatStatusSummary {
  id: string;
  status: ChatStatus;
  task_status?: string;
  updated_at: string | null;
  message_count: number;
}

export interface ChatUpdateRequest {
  name?: string;
  pinned?: boolean;
  task_status?: string;
  meta?: Record<string, unknown>;
}

export interface ChatDeleteResponse {
  success: boolean;
  chat_id: string;
}

// Legacy Session type alias for backward compatibility
export type Session = ChatSpec;
