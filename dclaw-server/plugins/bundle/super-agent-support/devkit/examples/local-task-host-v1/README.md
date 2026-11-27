# Local helper task API example

Declare local execution only when the Agent has real local work. The Agent
chooses its business operation and parameters; the local helper executes the
data-plane task. The example uses `video.render` as an **illustrative private
capability ID**. Replace it with a registered and granted capability from the
current target environment; do not assume this name is installed.

| Step | Public Host call | Caller supplies | Trusted success evidence |
|---|---|---|---|
| 1 | `local.task.start/1` | Granted `capability_id`, declared input, stable `idempotency_key`, optional file bindings | `local.task.receipt/1` with real `task_id`, same capability and key, accepted task status |
| 2 | `local.task.read/1` | Only the task ID from step 1 | Same task/capability/key; `queued`, `running`, `awaiting_input` and `cancelling` are not finished |
| 3 | `local.task.read/1` after execution | Same task ID | `succeeded`, opaque `artifact_ids` and `result_sha256`; Agent applies its own business acceptance checks |

```python
from devkit.local_task_api_demo import start_local_task, read_local_result

task_id = await start_local_task(
    host, capability_id=registered_capability_id,
    input_data=validated_private_input, idempotency_key="render-revision-1",
)
# After a later trusted read shows success:
artifact_ids = await read_local_result(
    host, task_id=task_id, capability_id=registered_capability_id,
    idempotency_key="render-revision-1",
)
```

The code validates the closed request and receipt schemas in
`schemas/local-task-host-v1/`. Copy the schemas and `jsonschema` dependency
into a signed Agent if adapting this reference at runtime. The Host injects
tenant, user, installation, release, conversation and invocation scope; none
belongs in the request. `not_found` also covers out-of-scope task IDs. For
`unavailable`, `rejected`, lost responses or unknown status, retain the same
key and task ID, check the helper status and stop downstream processing. Never
change the key to blindly start another task. `local.task.cancel/1` takes the
same `{ "task_id": ... }` request, but cancellation is a separate explicit
business decision.
`task-success.sample.json` contains Schema-valid start/read requests and
accepted/success receipts with one stable key. Its hashes and IDs are examples.

Public FFmpeg, Python, Node.js and similar components come from the plugin's
versioned Component Registry and are installed on demand by the local helper.
An Agent's private capability package is signed and registered separately.
Neither the registry nor the helper decides the Agent's business workflow.
