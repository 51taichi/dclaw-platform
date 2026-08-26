// Multi-agent management types

import type { ModelSlotConfig } from "./provider";

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir?: string | null;
  enabled: boolean;
  agent_type?: "standard" | "sealed";
  scope?: "local" | "global";
  version?: string | null;
  availability?: "available" | "unavailable";
  capabilities?: AgentCapabilities;
  active_model?: ModelSlotConfig | null;
}

export interface AgentCapabilities {
  invoke: boolean;
  public_metadata?: boolean;
  inspect: boolean;
  edit: boolean;
  clone: boolean;
  export: boolean;
  download: boolean;
  trace: boolean;
}

export interface AgentListResponse {
  agents: AgentSummary[];
}

export interface ReorderAgentsResponse {
  success: boolean;
  agent_ids: string[];
}

export interface AgentProfileConfig {
  id: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  approval_level?: string;
  active_model?: ModelSlotConfig | null;
  channels?: unknown;
  mcp?: unknown;
  heartbeat?: unknown;
  running?: unknown;
  llm_routing?: unknown;
  system_prompt_files?: string[];
  tools?: unknown;
  security?: unknown;
}

export interface CreateAgentRequest {
  id?: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  language?: string;
  skill_names?: string[];
  active_model?: ModelSlotConfig | null;
}

export interface AgentProfileRef {
  id: string;
  workspace_dir: string;
}

export interface AgentPackagePreview {
  id: string;
  name: string;
  description: string;
  root_path: string;
  agent_json_path: string;
  skills: string[];
  files_count: number;
  warnings: string[];
  has_conflict: boolean;
  suggested_id?: string | null;
}

export interface AgentPackageImportResult {
  imported: boolean;
  agent_id: string;
  name: string;
  workspace_dir: string;
  skills: string[];
  files_count: number;
  warnings: string[];
}
