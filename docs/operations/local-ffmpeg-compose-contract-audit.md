# Local FFmpeg composition contract audit (2026-11-11)

## Scope and observed state

This audit does not change the DClaw main service or send a business turn. The
production support plugin reported version 1.18.28. Component Registry v6 has
an available Windows x64 `ffmpeg` component (`ffmpeg`, `ffprobe`,
`media.transcode`), but that component is not a `local.task.start/1` package.
The registered task packages at inspection were `luyu.video.production`
0.1.1, `digital-human.media.transfer` 0.1.1, and `luyu.dazibao.compose`
2.0.0. None declares a generic, ordered multi-MP4 composition input and
result contract. There is no reusable generic concat capability ID or package
version to give to the Agent developer.

The helper 1.4.4 device record for user 57 had `capabilities_json=[]` and
`last_seen=2026-11-11T12:00:15Z`. Its persisted `online` field does not prove
an active connection: the runtime also requires the device ID in its in-memory
connection set. A user-authenticated `local_capabilities_list` response and
an exact-version `local_runtime_prepare` receipt are still required. No
installation or registration receipt exists for the proposed concat task.

## Existing trusted preparation semantics

`local_capabilities_list` returns capabilities actually reported by devices
with live connections for the authenticated user. `local_runtime_prepare`
first resolves a registered task package, then checks a compatible live
device. It returns `ready` only when that device reports the exact
`capability_id`, `package_id`, and `package_version`; otherwise it sends
`runtime.prepare` and returns `preparing`. The helper must subsequently
report the installed capability before `local.task.start/1` can select it.
These responses are currently available through the user-scoped local MCP
tools, not through a signed Agent Host readback. The Host provides
`local.task.start/1`, `local.task.read/1`, and `local.task.cancel/1` only.
An Agent must not infer installation from model candidates, a persisted
device flag, or a `preparing` receipt. A trustworthy signed-runtime route
requires separately cataloged, granted Host list/prepare capabilities that
return the plugin service's exact responses under the current user identity.

## AIGC-to-local resource gap and minimum contract

`aigc.task.snapshot/1` binds installation and conversation and returns
successful generation asset IDs and kinds, but no local-readable resource.
The existing AIGC asset service can authorize an owner, verify a canvas/node
binding, and create a short OSS GET URL. Its ordinary signed-URL route is not
scoped to a material task or an Agent installation. `local_file_bindings`
accepts only device-issued `local_file_ref`, so it cannot carry a generated
server-side video asset. Helper 1.4.4 does not implement an AIGC asset
binding. This is a missing platform contract, not a reason to ask customers
to download all videos manually.

The minimum safe extension is a **trusted start binding**, with no download
URL returned to the Agent or model:

```json
{
  "capability_id": "<registered-composition-capability>",
  "idempotency_key": "<stable-revision-key>",
  "input": {"ordered_clips": ["clip_01", "clip_02"]},
  "aigc_asset_bindings": [
    {"slot": "clip_01", "material_task_id": "<task-id>", "asset_id": "<video-asset-id>"},
    {"slot": "clip_02", "material_task_id": "<task-id>", "asset_id": "<video-asset-id>"}
  ]
}
```

The platform must reject duplicate slots, missing clips, reordered slot maps,
more clips than its explicit limit, cross-task assets, a different user,
installation, conversation or expert release, failed/cancelled generations,
non-video assets, and missing source files. It must resolve each asset against
the bound material task's successful generation jobs and canvas/node binding,
not merely accept a user-owned asset ID. It should issue a read-only URL with
an explicit short expiry (for example, ten minutes) only after all checks pass.
For local-only assets, an authenticated plugin-owned streaming endpoint or
equivalent short-lived object copy is needed; a `file://` path is not usable
from the customer's machine. The URL is sent over the authenticated device
channel only, not stored in the public task input, response, model prompt, or
logs. The helper downloads into a task-local staging directory, enforces size
and digest limits, rejects redirects to unapproved hosts, and reports transfer
failure before running FFmpeg. Expiry during a download requires a bounded
platform refresh, never a permanent URL. Cancellation revokes pending fetches.

The Agent's explicit `ordered_clips` list determines concat order. The Runner
validates the staged clip set and produces one local MP4. `local.task.read/1`
must eventually return `succeeded`, opaque final `artifact_ids`, and
`result_sha256`; the helper's managed-artifact action opens the final local
file. Readback after a failed or cancelled task must retain the terminal
status and must never claim a finished artifact. This contract needs a plugin
and helper implementation, a device protocol version, security tests, and a
real task acceptance run. It is not supplied by the Pack validator fix.

## Developer artifact and registration handoff

With no generic concat task registered, the developer must provide a
deterministic HTTPS-hosted Windows x64 ZIP, final size and SHA-256, a complete
descriptor with exact `capability_id`, `package_id`, version, entrypoint,
min Runner version, public `ffmpeg` component requirement/export binding,
input/checkpoint/result schemas, permissions and limits, a Base64 Ed25519
signature over canonical descriptor JSON, `signer_id`, and the separate
public key. The private key remains with the developer. The HTTPS host must
be reachable by the customer's network and allowed by descriptor policy.

An authorized plugin administrator registers the signer at
`POST /api/super-agent-support/capability-packages/signers` and the signed
descriptor at `POST /api/super-agent-support/capability-packages/register`.
Registration returns the exact package and capability identity. Only then
can the authenticated user call `local_runtime_prepare`, wait for the helper's
exact-version capability report, and run a real task. Public FFmpeg is reused;
it must not be copied into a second private component registry entry.

## Acceptance status

Developer Pack 1.10.22 corrects the `required` declaration gate and is
verified locally across `validate`, `test`, `capability-build`, and `build`.
Production download, signer registration, task registration, device
installation, AIGC transfer, and a real composition task remain unverified.
The exact missing inputs are the developer's final artifact/descriptor/key,
the platform resource-binding implementation and helper support, a live
user-scoped device report, and a user-authorized test task. No business turn
is authorized by this audit.

## Source implementation update (2026-11-12)

Support plugin 1.18.29 and Local Helper 1.4.5 close the generic
AIGC-to-local resource gap with two separately granted Host capabilities:
`aigc.task.assets.list/1` lists successful assets bound to the current user,
installation, conversation, workflow and canvas; `aigc.task.assets.localize/1`
accepts a structured usage plan and delivers the selected assets over the
authenticated device channel. Signed ten-minute OSS URLs are neither returned
to the Agent/model nor persisted in local-task input. The helper verifies
available size/digest metadata, computes the resulting digest, writes
intermediate assets under `res/`, declared final outputs in the task root, and
records `assets.json` for downstream tools.

This source implementation does not register a composition capability and
does not itself run FFmpeg. A Super Agent still needs a separately granted,
registered local composition capability for that next step. At the time of
this update no image, plugin archive, Helper installer, service restart or
production deployment has been performed.
