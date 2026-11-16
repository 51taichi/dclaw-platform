# DClaw Super Agent DevKit

Version 1.9.28 adds `schemas/local-ffmpeg-task-plan-v2/` and a complete-file
two-clip example. `plan_version=2` omits both trim fields for a complete clip;
one-sided boundaries use the actual file start or end, and two boundaries
select a bounded interval. Existing version 1 schemas and
requests are unchanged. Support plugin 1.18.50 and Helper 1.4.10 are required
for version 2; package version `0.1.0` remains compatible.

Version 1.9.27 adds the closed `aigc.assets.bind.result` Helper reply to
`schemas/super-agent-support-v1/device-message.schema.json`. A bound reply
contains ordered slot/file metadata; a rejected reply carries one stable
`LOCAL_SOURCE.*` code. Support plugin 1.18.49 accepts either result and bounds
the device wait to 150 seconds. Helper 1.4.9 and the Agent bind request are
unchanged.

Version 1.9.26 documents the shared `dclaw.ffmpeg.task.plan` structured
task. The Agent submits bound clips, trim/crop plan and output properties; the
Helper builds FFmpeg arguments. It reuses the existing Host task contracts,
requires Helper 1.4.9, and replaces the unshipped raw command example.

Version 1.9.24 adds the sealed Host `local.runtime.prepare/1` bridge for
exact-version Local Helper package preparation. Declare it with
`local.execution.session/1`; call `host.call` with a registered `capability_id`
and wait for `ready` before `local.task.start/1`. No session token belongs in
the Agent request. See `schemas/local-runtime-prepare-v1/`,
`local_runtime_prepare_api_demo.py` and `examples/local-runtime-prepare-v1/`.
It requires Support plugin 1.18.45 and a newly authorized Agent release.

Version 1.9.23 adds `local.task.outputs.bind/1` for sealed Agents to reuse
verified files from a succeeded localization task in the next local task. See
`schemas/local-task-outputs-bind-v1/`, `local_task_outputs_bind_api_demo.py`
and `examples/local-task-outputs-bind-v1/`. It requires plugin 1.18.44 and
Helper 1.4.7; bind and start must occur in one invocation.

Version 1.9.22 adds `developer.local-task.diagnostics.read/1` for the signed-in
expert owner. Use `local_task_diagnostics_api_demo.py --task-id ID` or
`--invocation-id ID` to inspect redacted AIGC localization tasks across the
same expert's installations. New Helper 1.4.6 records a safe failure stage,
category and version; older tasks mark missing detail as historical. AIGC
localization now requires Helper 1.4.6. Existing Agent request and receipt
schemas are unchanged.

Version 1.9.21 keeps the AIGC localization request and receipt schemas unchanged.
The Host verifies that each selected OSS object is publicly readable, then sends
its stable HTTPS URL without an expiration query to the Local Helper. A private
or unavailable object fails before task acceptance with
`ASSET_PUBLIC_DOWNLOAD_UNAVAILABLE`; the Agent still receives no URL.

Version 1.9.20 adds `developer.runtime.diagnostics.by-reference/5` for the
signed-in expert owner. `blocker` reports a recorded Host stage, safe error
code, field constraint, responsibility and recovery action. Historical generic
exceptions without retained detail remain explicitly unknown. Use
`runtime_diagnostics_api_demo.py --include-blocker --invocation-id ID`.
Schemas are in `schemas/runtime-diagnostics-v5/`; v4 stays unchanged.

Version 1.9.19 adds `developer.runtime.diagnostics.by-reference/4` for both
failed and completed turns. The owner-scoped read returns a redacted Host
operation timeline, exact-scope local task acceptance and its current stored
terminal status, runtime outcome and transaction status. A prior release
without Host operation traces reports `not_recorded` for those events; a task
table read is independently marked available or unavailable. Use
`runtime_diagnostics_api_demo.py --include-completed --invocation-id ID`.
The response and error schemas are in `schemas/runtime-diagnostics-v4/`.

Version 1.9.18 adds the closed `aigc.task.binding.resolve/1` schemas and
`recover_existing_task` demo. The Host resolves one existing task through a
committed compatible installation chain under the same user and conversation.
An ambiguous, missing or unauthorized match does not create a canvas.
The signed-in expert owner can use `aigc_binding_api_demo.py` to read the same
binding, whether the Host persisted its creation event, and whether current
workspace state contains the exact task ID. The API returns no media or text.

Version 1.9.17 specifies the unambiguous legacy read-only receipt: a
customer-completed task returns top-level `status=ACCEPTED`,
`completion_source=customer`, `review_performed=false`, and
`write_applied=false`; unfinished tasks return their persisted status and
require customer action. Exact installation, conversation, and task ownership
remain mandatory.

Version 1.9.16 keeps direct customer completion as the only AIGC acceptance
path. New and updated Agents must not depend on review writes. For already
signed Agents that still declare `aigc.review.complete`, the Host may expose an
`aigc_task_review` compatibility tool that only reads the exactly bound task
status. It never observes media, invokes model review, or writes a decision.
New `aigc.review.complete` writes remain retired.

Version 1.9.15 documents direct customer completion of exactly bound AIGC
tasks. The platform reaches `ACCEPTED` without invoking Agent review or
requiring the Agent package to declare `aigc.asset.submit`; legacy submitted
and reviewing snapshots remain readable.

Version 1.9.14 adds `aigc.task.assets.list/1` and
`aigc.task.assets.localize/1`. A Super Agent can list successful assets bound
to its current AIGC material task, assign each asset a structured usage, slot,
order and destination, then request delivery to the connected DClaw Local
Helper. Stable public source URLs remain inside the trusted Host-to-device
channel; they are not returned to the Agent or persisted in its local-task input.
Localization requires Helper 1.4.5 or newer. Asset `order` values are unique
within a request, and a dispatch disconnect produces a terminal failed receipt
instead of leaving a queued task.

Version 1.9.13 adds closed schemas for
`developer.runtime.diagnostics.by-reference/3` and
`developer.runtime.diagnostics.search/1`, plus
`runtime_diagnostics_api_demo.py`. The owner can find failures in a bounded
time window, then read the final Host rejection's stable code, safe field,
constraint, and recovery action. Historical missing details remain
`not_recorded`. Both endpoints require local sign-in, are audited, and share
the 30 reads/minute limit. Existing v1/v2 response schemas are unchanged.
After signing in locally, run:

```bash
python runtime_diagnostics_api_demo.py --base-url https://dclaw.deepmega.cn \
  --agent-id your_agent_id --invocation-id 0123456789abcdef0123456789abcdef
```

Without an invocation ID, use `--start` and `--end` with UTC ISO-8601 values;
pass the returned `next_cursor` with `--cursor` for the next page. The command
reads `DCLAW_ACCESS_TOKEN` from its environment and never prints the token.

Version 1.9.12 adds `aigc_workflow_api_demo.py` and `local_task_api_demo.py`
with call-order, live-catalog, bound-result, idempotency and terminal-result
examples under `examples/aigc-workflow-v1/` and `examples/local-task-host-v1/`.
The AIGC catalog/create calls are dynamically granted model tools in
`agent_loop`; the AIGC snapshot and local tasks are direct Host calls. These
examples add no new Host capabilities. Keep their schemas and `jsonschema`
dependency with a signed Agent when adapting them at runtime.

Version 1.9.11 adds the runnable direct Host reference
`interaction_card_api_demo.py`. Its `create_card` covers all four published
components. It obtains the selected live card Schema,
validates the card and approved business option IDs, creates the card with a
stable idempotency key, and verifies the persisted `created` receipt before
returning an interaction ID. See `examples/interaction-host-v1/README.md` for
the call and required pre-publication tests. This is reference source for the
Agent runtime, not a new Host capability.

Version 1.9.10 adds a complete `single_select` live catalog fixture at
`fixtures/interaction-host-v1/single-select-live-catalog.json` and a Draft
2020-12 validation reference at `validate_live_card.py`. The reference requires
the separate `jsonschema>=4.20,<5` Python package in the developer test
environment. Do not assume it is installed in a sealed Agent runtime; package
the chosen runtime validator with the signed Agent when needed. The target
Host catalog remains authoritative over this offline fixture.

Version 1.9.9 adds direct Host `interaction.capabilities.list/1` and
`interaction.card.create/1` request/response schemas in
`schemas/interaction-capabilities-list-v1/` and
`schemas/interaction-card-create-v1/`. The successful `single_select` call,
result and `created` receipt are in
`examples/interaction-host-v1/single-select-success.json`; see that example's
README for live Schema location, input policy and idempotent replay rules.

Version 1.9.8 adds `developer.runtime.diagnostics.by-reference/2` at
`GET /api/user/super-expert-publishing/runtime-diagnostics/v2/references/{invocation_id}?agent_id=...`.
The signed-in developer must own that expert; a customer-visible invocation
reference resolves only within the same tenant and expert. The response keeps
the v1 fields and adds bounded `failure_events`, `final_blocker`, and
`unrecorded_fields`. Early errors followed by a successful `agent.execute`
are marked recovered. A Host call failure takes precedence over a later Agent
trace that merely reports the failed Host result. Historic provider metadata
that was not recorded stays null; no model text or request body is returned.
New card validation failures expose only a safe field path, constraint code,
and contract ID. New provider failures retain only HTTP status and stable
code/param when the provider supplies them.
The endpoint is audited and limited to 30 reads per actor per minute.
The v1 route and schemas remain available unchanged.

Version 1.9.7 adds optional `aigc.task.snapshot/1`, `local.task.start/1`,
`local.task.read/1`, and `local.task.cancel/1` Host contracts with closed
schemas. It also adds `developer.runtime.diagnostics.by-reference/1` for a
signed-in developer who owns the expert. Existing signed releases are unchanged.

Version 1.9.6 adds the optional Host call `interaction.card.read/1` with closed
request and response schemas in `schemas/interaction-card-read-v1/`. Pass only
the persisted `interaction_id`; the Host supplies the trusted installation,
task and tenant scope. The result returns the stored status and, only after
submission, the normalized answer and its `interaction.card.receipt/1`.
Unknown and out-of-scope IDs both return `result=not_found`. No idempotency key
is needed for this read. Earlier card tools and signed packages are unchanged.

Version 1.9.5 adds closed `interaction.card.receipt/1` schemas under
`schemas/interaction-card-receipt-v1/`. The `interaction_card_create` tool and
card submission HTTP response include a receipt for the persisted transition.
`session.context.interaction_receipts` contains the 20 most recently updated
pending or submitted cards for the trusted installation and task, with no
answer body. Read `interaction_card_status(interaction_id)` for the submitted
answer. Free-text `user_input` is display text and cannot prove submission.
`developer.runtime.diagnostics.read/1` now includes sanitized execution stage
timestamps, durations and candidate shape on newly recorded failures. Each
stage identifies `source=host` or `source=agent`; an Agent trace never proves a
Host transaction committed. Runtime invocation timing includes sandbox startup
and execution, while queue time is not currently recorded.

Version 1.9.4 adds an activation preflight receipt to the closed self-service
publishing response schema. The Host checks all existing task-state contracts
before switching the active Release; a conflict leaves the previous Release
active. Existing signed packages and the sealing format are unchanged.

Version 1.9.3 validates optional signed `agent/state-contract.json` for
`workspace.state.continuity/1`. Stateful Agents declare a stable `format_id`,
`schema_version`, and `filename_template` containing exactly one
`{identity_sha256_24}` placeholder. Compatible releases with the same signer
and state format resume the complete task state before the next business turn;
incompatible releases fail closed. See
`schemas/workspace-state-continuity-v1/state-contract.schema.json`.

Version 1.9.2 excludes Python bytecode caches from signed packages and adds a
schema for owner-scoped developer diagnostics. The optional
`runtime.failure.read/1` Host capability has closed request/response schemas
in `schemas/runtime-failure-v1/`. A signed
Agent must declare and be granted this capability; the request is `{}`. The
Host checks the trusted task owner and returns only the latest sanitized
failure for the same tenant and Agent across installations within 30 days.
`no_record` is a normal response. Existing signed Agents need no change.

`agent.execute` accepts `response_format="json_object"` only in default
candidate mode. This requests a JSON object from the provider, but does not
enforce an Agent business schema or guarantee visible text. It cannot be
combined with `execution_mode="agent_loop"`. The Host has no public
per-call `max_tokens`, thinking, or JSON Schema control argument.

Version 1.9.0 adds owner-scoped self-service publishing for signed-in DClaw
developers. `keygen` keeps the private key local; `publish register-signer`
registers only the public key, and `publish upload` validates and globally
activates a `super_expert_public` package. The CLI reads the signed-in user's
short-lived token from `DCLAW_ACCESS_TOKEN`; never send it in chat or place it
inside an Agent package. The package's business Python runs in a plugin
sandbox and has only the sealed runtime's restricted tools.

Version 1.8.3 publishes plugin-managed local-helper update actions and closed
request/response schemas. It retains stable installation credential slots,
`agent.outbound.stream/1`, and `resource.exchange/1` in addition to the
provider-neutral controlled
HTTPS transport for sealed Super Agents. The Agent owns provider selection,
request parameters, idempotency, polling, retries, fees, and response
interpretation. The transport resolves an installation-scoped
`credential_ref`, enforces its domain, method, and scope policy, and injects
the secret only at the final network boundary. Long-term provider credentials
are never returned to the Agent, model, workspace, logs, or local helper.
Presigned upload targets now have a dedicated closed response schema. HTTPS
streaming requests can optionally extract one JSON Pointer string and strictly
decode its Base64 payload directly into temporary object storage; the encoded
or decoded media never enters the Agent response.

The 1.6.0 public Component export bindings for Runner 1.3.0 remain compatible,
as do the 1.4.1 business service identity contracts. Component registry
commands continue to call `dclaw.super-agent-support` directly and require no
DClaw management page or server source.

Capability descriptors may bind a declared public Component export to a
process environment variable with `component_exports`. Variables must use the
`DCLAW_COMPONENT_*` namespace, the Component must also appear in
`public_components`, and the capability must require Runner 1.3.0 or newer.
Runner resolves the signed relative export inside the installed Component and
fails closed for undeclared Components, missing exports, duplicate variables,
pre-existing variables, or paths outside the Component root. See
`fixtures/public-components/component-export-cases.json`.

`operation-catalog.json` fixes the public client keys, MCP tool names,
Streamable HTTP endpoint and JSON-RPC sequence. Controlled outbound requests
may omit a body or provide exactly one of `json_body` and `text_body`. The
platform injects exactly one `Authorization: Bearer <assertion>` header;
Agent-supplied authorization and case-insensitive duplicate headers are
rejected.

`agent_outbound.request` does not use the business-service issue/audience
flow. Its credential is installed through the authenticated
`/api/super-agent-support/agent-outbound/credentials` endpoint with explicit
scope, Agent, installation, domain, method, and authentication-header policy.
Sync.so-style API keys use authorization type `header` with name `x-api-key`;
Bearer providers use type `bearer`. The sealed Agent retains only the returned
stable `credential_slot` for new releases or the compatible opaque
`credential_ref` for existing signed Agents.

Business services that verify with the public JWK set must use
`business_identity_verifier.py` or an equivalent durable replay cache. Every
accepted `(issuer, jti)` must be stored atomically until `exp + clock_skew`;
signature validity alone never establishes replay safety. The replay contract
fixture is in `fixtures/business-identity/replay-cases.json`. Verification must
also supply and match the expected issuer, audience, Agent, service,
installation, release, and non-empty minimum scope set.

Receivers must pass the raw list of all `Authorization` header field values to
`extract_bearer_assertion` before signature verification. It accepts exactly
one `Bearer <assertion>` value and rejects missing, duplicate, comma-combined,
non-Bearer and empty values. Do not use a framework accessor that silently
combines or discards duplicate headers.

This directory is a standalone developer kit. It does not require DClaw
server source code.

Supported development environments:

- CPython 3.10-3.13
- Windows x64
- macOS x64 and ARM64
- Linux glibc x64 and ARM64

Run `bootstrap.ps1` on Windows or `bootstrap.sh` on macOS/Linux. The scripts
create `.venv`, verify every bundled wheel, and install the pinned encryption
dependencies without using a package index.

After bootstrap:

```text
.venv/Scripts/python.exe dclaw_agent_devkit.py contracts   # Windows
.venv/bin/python dclaw_agent_devkit.py contracts           # macOS/Linux
```

Signing keys are never read, copied, or printed by the bootstrap scripts.
See `THIRD_PARTY_LICENSES.md` for bundled dependency licenses.
