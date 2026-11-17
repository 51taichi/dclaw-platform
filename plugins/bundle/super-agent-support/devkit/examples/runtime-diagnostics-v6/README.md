# Runtime and Local Task Diagnosis

Use the signed-in expert owner's access token with
`runtime_diagnostics_api_demo.py --base-url https://dclaw.deepmega.cn
--agent-id AGENT_ID --invocation-id INVOCATION_ID --root-cause`.
The demo validates the closed v6 response Schema. This is a developer-only
read; sealed experts do not receive this capability.

The response joins the authorized runtime trace and any accepted local tasks
for the same invocation. `findings[]` may contain several failures; do not
interpret the first array item as a unique root cause. Each item identifies its
layer, stable code, responsibility, recovery action, and evidence quality.
`specific_recorded` means a safe specific code was retained.
`first_observed_only` means the platform observed a failure but did not retain
its internal cause; `HOST_INTERNAL_ERROR` is in this category.
`historical_detail_not_recorded` means old records lack enough detail.
`no_failure_recorded` does not prove that no failure occurred outside the
retained evidence. A local task can fail after the expert turn has completed.

The reader checks expert ownership, original session tenant/user/expert,
source installation grant, and task scope. It works across authorized releases
of the same expert. Access is limited to 30 reads per minute per actor and
30 days of retained evidence; reads are audited with hashed actor/reference.
No response includes model text, conversation content, request values, URLs,
file paths, stack traces, or tokens. An unknown or expired invocation returns
`no_record`; an unrelated expert returns HTTP 404. If a source cannot be read,
the API returns HTTP 503 rather than presenting missing evidence as a clean run.
