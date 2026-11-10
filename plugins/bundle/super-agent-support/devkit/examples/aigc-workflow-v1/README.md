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
