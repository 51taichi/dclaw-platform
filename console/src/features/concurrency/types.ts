export interface ConcurrencyBreakdownRow {
  running: number;
  waiting: number;
  max_running: number;
}

export interface ConcurrencySnapshot {
  sampled_at: string;
  open_api: {
    running: number;
    max_running: number;
    waiting: number;
    max_waiting_per_agent: number;
    max_waiting_per_api_key: number;
    wait_timeout_seconds: number;
    by_agent: Array<ConcurrencyBreakdownRow & { agent_id: string }>;
    by_api_key: Array<ConcurrencyBreakdownRow & { api_key: string }>;
  };
  platform_tasks: { running: number; max_running: number };
  model_calls: { running: number; max_running: number; available: number };
}
