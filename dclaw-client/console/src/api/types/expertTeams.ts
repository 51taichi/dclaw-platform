export interface ExpertTeamMember {
  key: string;
  agent_id: string;
  display_name: string;
  role?: string;
  avatar?: string;
  description?: string;
  default_skills?: string[];
}

export interface ExpertTeamWorkflowStage {
  key: string;
  name: string;
  members: string[];
  parallel?: boolean;
  instruction?: string;
}

export interface ExpertTeamTemplate {
  id: string;
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  icon?: string;
  enabled?: boolean;
  leader_agent_id: string;
  members: ExpertTeamMember[];
  workflow: ExpertTeamWorkflowStage[];
  usage_count?: number;
  source?: string;
  sort_order?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExpertTeamMemberRun {
  id: string;
  run_id: string;
  member_key: string;
  agent_id: string;
  display_name: string;
  role?: string;
  avatar?: string;
  state: "pending" | "running" | "completed" | "failed" | "cancelled";
  stage_index?: number;
  task_id?: string | null;
  child_session_id?: string | null;
  input_text?: string;
  output_text?: string | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExpertTeamRun {
  id: string;
  team_id: string;
  root_chat_id: string;
  root_session_id: string;
  user_id: string;
  state:
    | "pending"
    | "running"
    | "paused_insufficient_balance"
    | "completed"
    | "failed"
    | "cancelled";
  input_text?: string;
  final_summary?: string | null;
  error?: string | null;
  next_member_key?: string | null;
  required_credits?: number | null;
  team?: ExpertTeamTemplate | null;
  members: ExpertTeamMemberRun[];
  created_at?: string | null;
  updated_at?: string | null;
  finished_at?: string | null;
}
