# Local task diagnostics

The signed-in owner of an expert can query one AIGC localization task by its
local task ID or all localization tasks from one invocation. The API reads
historical installations of that same expert after checking the original
customer session and grant. It never returns asset URLs, filenames, paths,
request bodies, or exception stacks.

```bash
python local_task_diagnostics_api_demo.py \
  --base-url https://dclaw.deepmega.cn \
  --agent-id your_agent_id \
  --task-id 0123456789abcdef0123456789abcdef
```

Use `--invocation-id` instead to find tasks created by a turn. The token is
read from `DCLAW_ACCESS_TOKEN` in the developer's local environment. A task
created before Helper 1.4.6 may retain its terminal error code but have
`failure_evidence=historical_detail_not_recorded`; the Helper's internal
first failure cannot be reconstructed from that code. `device_online_now`
is a current observation, not proof of connectivity at execution time.
`no_record` also covers unauthorized and expired records. Reads are audited,
limited to 30 per minute per account, and retained for 30 days.
