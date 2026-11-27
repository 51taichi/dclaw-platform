# Local task diagnostics v2

The signed-in owner of a Super Agent can inspect any local task from that
expert by task ID or invocation ID. This includes public FFmpeg tasks and
private capability packages. The API verifies the original customer session,
tenant, user, expert and installation grant before returning a task. It never
returns file references, download URLs, paths, task inputs, media, exception
messages or stacks.

```bash
python local_task_diagnostics_api_demo.py \
  --base-url https://dclaw.deepmega.cn \
  --agent-id your_agent_id \
  --api-version 2 \
  --task-id 0123456789abcdef0123456789abcdef
```

Use `--invocation-id` to read all authorized local tasks in one invocation.
The demo reads the signed-in developer's token from `DCLAW_ACCESS_TOKEN` and
validates the response against the v2 Schema. `first_failure_phase` and
`exception_category` each have an evidence field: `recorded` means the Helper
actually reported it; `historical_detail_not_recorded` means it cannot be
reconstructed. An old `ObjectDisposedException` type may support a recorded
`json_lifetime` category while its exact phase remains unknown.

`no_record` covers missing, unauthorized and expired tasks. Diagnostics are
retained for 30 days, limited to 30 reads per minute per developer account and
audited without customer content. The original v1 endpoint remains available
for AIGC localization callers.
