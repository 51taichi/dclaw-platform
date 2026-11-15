# Sealed Host local runtime preparation

Declare `local.execution.session/1` and `local.runtime.prepare/1` in the signed
manifest. To start a task later, also declare `local.task.start/1`; declare
`local.task.outputs.bind/1` when reusing a prior localization task. The
administrator must separately register the private capability package.

During an authorized sealed-expert turn, call the Host directly:

```python
from local_runtime_prepare_api_demo import prepare_local_runtime

receipt = await prepare_local_runtime(
    host, capability_id="example.video.compose",
    package_id="example.video.compose", package_version="0.1.0",
)
if receipt["status"] != "ready":
    return receipt
# Only now bind prior outputs and call local.task.start/1.
```

The request is `{"capability_id": "example.video.compose"}` with optional
`device_id` when a trusted prior binding receipt identifies the device holding
the source files. The Host limits selection to that user's online devices;
an unknown or offline device returns `device_not_ready`. For a multi-device
workflow, bind once to learn the source device, prepare on that device, then
bind again if the earlier file references expire before starting the task.
The Host uses the trusted turn's user, tenant, expert, installation and
release. The Agent never sends a `dclaw_session_token`, artifact URL or signer
key. A missing grant is rejected by the Host before dispatch. The MCP tool
`local_runtime_prepare` remains available to existing user-scoped MCP callers;
it is a different transport from this sealed Host capability.

`preparing` means the Helper was asked to install the exact signed package;
call again after its capability report. `device_not_ready` requires the user to
open DClaw, and `runner_update_required` requires a Helper update. Only
`ready` proves the online Helper reported the exact `capability_id`,
`package_id` and `package_version`. The Host does not start a local task.

Request and response schemas are in `schemas/local-runtime-prepare-v1/`.
`request.sample.json`, `preparing.sample.json` and `ready.sample.json` are
Schema-valid examples. The demo also rejects a registered version different
from the Agent's pinned private package version.
This Host capability requires Support plugin 1.18.45. Existing signed releases
are unchanged and must add the new declaration in a newly authorized release.
