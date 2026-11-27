# Reuse downloaded AIGC files in a later local task

Declare both `local.task.outputs.bind/1` and `local.task.start/1`. The source
must be a succeeded `aigc.task.assets.localize/1` task from the same tenant,
customer, conversation and expert, on the same online device. A prior
installation is accepted only through committed workspace continuity. The
Helper must be 1.4.7 or newer. This is an automatic expert path; a customer
choosing files with `file_selector` is a separate manual path.

In one invocation, call the sealed Host with a source task ID and selected
slots, then pass each returned `local_file_ref` to `local.task.start/1` as
`local_file_bindings`. The result preserves source `order` regardless of
request order. Each reference is scoped to the current invocation, installation
and device and expires after one hour. A later invocation must bind again.
Retrying bind may issue fresh equivalent references; it does not redownload
files or start a production task. Keep the same `local.task.start/1`
idempotency key when retrying task startup.

```python
from devkit.local_task_outputs_bind_api_demo import start_from_localized_outputs

receipt = await start_from_localized_outputs(
    host,
    source_task_id="localization-task-id",
    slots=["clip_01", "clip_02"],
    capability_id=registered_video_capability_id,
    input_data=validated_private_video_input,
    idempotency_key="render-revision-1",
)
```

`bound` proves the Helper rechecked the original manifest and selected files'
sizes and SHA-256 hashes. `not_found` hides out-of-scope task IDs;
`source_not_ready` means the source did not succeed; `rejected` gives a stable
device or file error code. The start receipt and subsequent `local.task.read/1`
remain authoritative for the new task. This operation does not register a
private video capability or claim FFmpeg output succeeded.
