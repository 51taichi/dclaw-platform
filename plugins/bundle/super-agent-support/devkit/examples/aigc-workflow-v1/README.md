# AIGC workflow and task card API example

This is a model-backed `image_generate` example. The AIGC workflow task card
is created by the granted AIGC workflow operation. It is **not** an
`interaction.card.create/1` question card. The signed runtime invokes
`agent.execute` with `execution_mode="agent_loop"` so the Host can register
the granted `aigc_workflow_catalog` and `aigc_workflow_create` model tools.
Do not set `response_format="json_object"` on that call.

| Step | Public call | Caller supplies | Trusted success evidence |
|---|---|---|---|
| 1 | `aigc_workflow_catalog(node_kinds=["image_generate"])` | Exact needed kinds | Live `catalog`, full `workflow_schema`, and executable `workflow_examples` |
| 2 | `aigc_workflow_create(task_key, content_revision, workflow)` | Stable logical key, positive revision, blueprint conforming to the live schema and model list | Persisted `event.event_type=aigc.task.created` plus matching task binding, real `material_task_id` and `canvas_id` |
| 3 | Customer uses the resulting AIGC task card | Customer action on the real canvas | Task status changes; creation alone is not generation or acceptance |
| 4 | `await host.call("aigc.task.snapshot/1", {"material_task_id": material_task_id})` | ID returned by step 2 | `found`, same material task/canvas, submitted status, successful node job and matching submitted asset ID |
| 5 | `await host.call("aigc.task.assets.list/1", {"material_task_id": material_task_id})` | Same bound task ID | Owner-scoped asset facts only; no source URL |
| 6 | `await host.call("aigc.task.assets.localize/1", usage_plan)` | Asset IDs from step 5 plus usage, slot, order, destination and a stable idempotency key | A scoped local-task receipt; the connected Helper downloads the selected files |

If a prior release created the canvas but failed to save the task ID, call
`aigc.task.binding.resolve/1` with the original `task_key` and optional
`content_revision`. An empty request succeeds only when exactly one owned AIGC
task exists in this conversation across committed compatible installations.
`found` returns the original `material_task_id`; use it with steps 4-6. The
Host checks the trusted tenant, user, expert, conversation, canvas owner and
committed continuity chain. `not_found`, `ambiguous` and `unavailable` stop
the workflow; never guess an ID from visible card text or create a duplicate.
New releases must declare and receive this optional capability before calling
it. The closed schemas are in `schemas/aigc-task-binding-v1/`.
The expert owner can run `aigc_binding_api_demo.py` against the authenticated
developer endpoint using the same session and key. A `found` response with
`current_workspace_references_task=false` confirms the Host task exists while
the current workspace state has no exact ID reference; it does not identify
which Agent branch omitted the write.

`devkit/aigc_workflow_api_demo.py` is a runnable contract reference for steps
1, 2 and 4. Its `catalog_tool` and `create_tool` arguments represent the
Host-registered model tools in a test harness. A sealed runtime does not
receive these Python callables directly: it requests them through
`agent.execute(execution_mode="agent_loop")`, then verifies the returned
task identity with the separate Host snapshot. The reference accepts only
live catalog models; the included tests use illustrative IDs and are not a
production provider list. The Host injects tenant, installation, conversation
and user scope. Never construct physical canvas, material task or asset IDs.
`submitted-snapshot.sample.json` is a complete Schema-valid read example:
the submitted asset ID must match a generated asset from a succeeded job on
the expected node and canvas. All IDs in that file are illustrative.

Use the same `task_key`, revision and blueprint for an uncertain retry. A
changed plan increments `content_revision`. On tool error, missing or
inconsistent binding, `not_found`/`unavailable` snapshot, pending generation,
failed job or unmatched asset, stop downstream work. Read the same task rather
than starting a duplicate. `aigc.task.snapshot/1` request/response schemas
are under `schemas/aigc-task-snapshot-v1/`; the catalog's workflow and node
schemas are live, so a static example cannot replace the target catalog.

The single submitted-asset helper is intentionally narrow. Multi-asset
workflows must correlate every required node, job and asset under the same
bound canvas and use the task's actual review submission contract.

For downstream local processing, first read the bound asset manifest and then
send an explicit plan. Do not invent asset IDs or pass URLs:

```python
manifest = await host.call(
    "aigc.task.assets.list/1",
    {"material_task_id": material_task_id},
)
assert manifest["status"] == "found"

receipt = await host.call("aigc.task.assets.localize/1", {
    "material_task_id": material_task_id,
    "idempotency_key": f"localize:{material_task_id}:revision-1",
    "assets": [
        {
            "asset_id": manifest["assets"][0]["asset_id"],
            "usage": "timeline_clip",
            "slot": "clip_01",
            "order": 0,
            "destination": "res",
        },
    ],
})
```

Allowed usages are `cover`, `timeline_clip`, `reference_image`,
`background_audio`, `voice_audio`, `subtitle`, `overlay`, and `final_output`.
Only `final_output` uses `task_root`; every other usage uses `res`. The receipt
is read with the existing `local.task.read/1` contract. A replay with the same
idempotency key and identical plan returns the original task; changing the plan
requires a new key. `order` is a non-negative integer and must be unique within
one localization request; request-array order has no semantic meaning. If the
device disconnects after task creation but before dispatch, the Host terminates
that task as `failed` with `LOCAL_GATEWAY.DEVICE_NOT_READY`; reconnect the
Helper and retry with a new idempotency key. The Host validates ownership and
task binding before it sends short-lived source URLs directly to Helper 1.4.5
or newer.
