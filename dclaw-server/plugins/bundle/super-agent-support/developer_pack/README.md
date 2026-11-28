# DClaw Super Agent Developer Pack

Version 1.10.51 bundles standard 2.73 and DevKit 1.9.36. Newly updated
experts can opt into stage-specific interaction, AIGC and Local Helper guides
with `capability.stage.enter/1`; the Host gates side effects by stage. The
business expert still owns stage decisions and customer authorization. Signed
legacy releases are unchanged.

Version 1.10.50 bundles standard 2.72 and DevKit 1.9.35. The four-card
reference maps a business answer shape to one real component type and checks
the model proposal before calling the existing Host APIs. Signed releases
and the published card Schemas remain unchanged.

Version 1.10.49 bundles standard 2.70 and DevKit 1.9.34. New and updated
experts use one model response for the business reply and optional card
proposal, with a same-turn text fallback when the card cannot be created.

Version 1.10.47 bundles standard 2.68 and DevKit 1.9.32. New releases that
declare `agent.execute` v2 use the governed Agent Loop by default and request
model-only generation with explicit `execution_mode="candidate"`. Existing
signed v1 releases retain their candidate default and remain compatible.

Version 1.10.46 bundles standard 2.67 and DevKit 1.9.31. Retired Release
membership no longer blocks an otherwise scoped, schema-compatible workspace
state continuation. Unbound legacy auxiliary JSON without a trusted identity is
ignored; a residual state binding remains a fail-closed scope conflict.

Version 1.10.45 bundles standard 2.66 and DevKit 1.9.31. Fixed model routes
are checked against the current catalog before runtime entry; model request,
stream and Agent execution timeouts become visible through existing authorized
diagnostics without exposing content. The DevKit machine schemas are unchanged.

Version 1.10.44 bundles standard 2.65 and DevKit 1.9.31. It publishes strict
`agent.execute` and `runtime.fail` contracts and safe failed-turn card
compensation. Existing valid calls and activated releases remain compatible.

Version 1.10.43 bundles standard 2.64 and DevKit 1.9.30. Developer runtime
diagnostics v6 joins authorized runtime and local-task evidence by invocation
ID and marks generic or historical failures without inventing a root cause.

Version 1.10.42 bundles standard 2.63 and DevKit 1.9.29. Public runtime health
now verifies the live worker, shared roots and Bubblewrap probe, and diagnostics
v5 safely attributes recorded runtime isolation failures to the platform.

Version 1.10.41 bundles standard 2.62 and DevKit 1.9.29. Developer local task
diagnostics v2 covers every authorized local capability, including public
FFmpeg tasks, while preserving the AIGC-only v1 endpoint. Helper 1.4.12
records safe stages for new task failures; older missing fields stay unknown.

Version 1.10.40 bundles standard 2.61 and DevKit 1.9.28. Public video plan
version 2 uses full bound clips when trim fields are omitted and accepts
open-ended or bounded explicit trims. Support plugin 1.18.50 and Helper 1.4.10 are needed for v2.
Version 1 plans and existing grants remain valid.

Version 1.10.39 bundles standard 2.60 and DevKit 1.9.27. Support plugin
1.18.49 accepts the Helper's closed `aigc.assets.bind.result` reply for
`local.task.outputs.bind/1` and returns a stable failure on device timeout.
The Agent request and Helper binary are unchanged.

Version 1.10.38 bundles standard 2.59 and DevKit 1.9.26 with the public
`dclaw.ffmpeg.task.plan` task contract, Schemas and Host API demo.
Agents submit a structured timeline with trusted file bindings; Helper builds
the FFmpeg arguments after exact-version runtime preparation.

Version 1.10.36 accepts every published `local_execution` capability in
`required` local Helper projects, including `local.runtime.prepare/1`.
Unlisted local capabilities still fail validation. The standard and DevKit
versions remain 2.57 and 1.9.24.

Version 1.10.35 bundles standard 2.57 and DevKit 1.9.24. Newly authorized
sealed Agents can call `local.runtime.prepare/1` through the trusted Host,
then wait for the Helper's exact-version `ready` report before starting a
local task. Existing signed releases keep their original grants.

Version 1.10.34 bundles standard 2.56 and DevKit 1.9.23. Sealed Agents can
bind verified files from a succeeded AIGC localization task directly into the
next local task on the same device with `local.task.outputs.bind/1`.

Version 1.10.33 bundles standard 2.55 and DevKit 1.9.22. Localization requires
Helper 1.4.6; the new owner-scoped local task diagnostic API reports recorded
Helper failure stages without exposing assets or local paths.

Version 1.10.32 bundles standard 2.54 and DevKit 1.9.21. AIGC material
localization sends publicly readable, stable OSS object URLs to the Local
Helper after owner-scoped selection and a public-read preflight.

Version 1.10.31 bundles standard 2.53 and DevKit 1.9.20. Localization
handoff checks report interaction, AIGC, Agent, Host, and Local Helper nodes
separately. Unknown Host exceptions are attributed to the platform without
exposing internal details.

Version 1.10.30 bundles standard 2.52 and DevKit 1.9.20. The owner-scoped
diagnostics v5 read gives a safe Host blocker and recovery action for new
AIGC localization failures while marking missing historical detail unknown.

Version 1.10.29 bundles standard 2.51 and DevKit 1.9.19. A signed-in expert
owner can read redacted Host operations for committed business-blocked turns
through diagnostics v4. Historical missing operation fields remain unknown.

Version 1.10.28 bundles development standard 2.50 and DevKit 1.9.18. The
optional `aigc.task.binding.resolve/1` contract finds one owned, existing
task across committed compatible installations; snapshot, asset listing and
localization accept that verified original task ID without recreating media.

Version 1.10.27 bundles development standard 2.49 and DevKit 1.9.17. The
legacy read-only AIGC compatibility receipt exposes customer completion as
`ACCEPTED` while explicitly stating that no Agent review or write occurred.

Version 1.10.26 bundles development standard 2.48 and DevKit 1.9.16. New and
updated Agents must not depend on review writes. Already signed Agents may use
the platform's same-name read-only compatibility tool to observe the strictly
bound customer completion state; it never performs or records Agent review.

Version 1.10.25 bundles development standard 2.47 and DevKit 1.9.15. Customer
completion of an exactly bound AIGC task is a platform action that reaches
`ACCEPTED` without Agent review or an Agent submit grant. Legacy submit/review
capability IDs remain recognizable to already published experts, but review
write execution is retired and historical review data is read-only.

Version 1.10.24 bundles development standard 2.46 and DevKit 1.9.14. It adds
the public AIGC asset handoff workflow, ownership boundary, minimum Helper and
plugin versions, historical-digest compatibility rule, and canonical Schema
and demo locations. Existing Agents that do not declare the new capabilities
are unchanged.

Version 1.10.23 bundles development standard 2.45 and DevKit 1.9.14. It adds
the owner-scoped AIGC asset manifest and Local Helper delivery contracts.
Intermediate assets are placed under `res/`; declared final outputs are placed
in the task root. Existing signed Agents and local-task contracts are unchanged.

Version 1.10.22 bundles development standard 2.45 and DevKit 1.9.13. It
accepts cataloged `local.task.*` Host capabilities alongside the required
local helper declarations. Unknown local capabilities remain invalid.

Version 1.10.21 bundles development standard 2.45 and DevKit 1.9.13. It
adds a redacted Host rejection lookup and a 24-hour failure-reference search
for the signed-in expert owner. Existing v1/v2 diagnostics and sealed Agents
retain their contracts.

Version 1.10.20 bundles development standard 2.44 and DevKit 1.9.12. The
interaction card, AIGC workflow task card and local helper task each have a
separate runnable API reference and documented failure gate. Existing Host
contracts and signed Agent releases are unchanged.

Version 1.10.19 bundles development standard 2.43 and DevKit 1.9.11. The
direct Host API demo shows the same catalog, validation, create and receipt
boundary for every newly built or updated Super Agent. It changes no existing
Host capability or signed Agent release.

Version 1.10.18 bundles development standard 2.42 and DevKit 1.9.10. It adds
the actual `single_select` live catalog fixture and full Schema validation
reference so Agent tests catch unsupported `$defs` and `$ref` before sealing.
The Host card contracts and existing signed Agent behavior are unchanged.

Version 1.10.17 bundles development standard 2.41 and DevKit 1.9.9. Direct
Host interaction catalog and card creation now have request/response schemas
and a verified `single_select` success example under `devkit/examples/`.
The live card schema remains at `components[].schema` in the Host catalog;
the public Component Registry is a separate local-helper dependency catalog.

Version 1.10.16 bundles development standard 2.40 and DevKit 1.9.8. New and
updated Agents generate internal business text first, then generate a separate
card draft from the live catalog and call the trusted Host create capability
after runtime validation. Existing signed Agents retain their card tool path.

Version 1.10.15 bundles development standard 2.39 and DevKit 1.9.8. It adds
the owner-scoped final-blocker diagnostics v2 contract and Agent-loop card
compatibility guidance. Version 1.10.14 added
the optional reference diagnostics, AIGC task snapshot, and local task Host
receipt contracts. Capability-package signer public keys require separate
plugin administrator trust registration before a signed descriptor is accepted.

Version 1.10.13 bundles development standard 2.37 and DevKit 1.9.6. The
standard now requires per-capability impact checks against active releases and
coordinated updates for every affected Super Agent before an incompatible
plugin contract can replace an existing one.

Version 1.10.12 bundles development standard 2.36 and DevKit 1.9.6. The
optional `interaction.card.read/1` Host call reads a card's persisted status,
normalized submitted answer and trusted receipt under the current installation
and task. Existing card tools and signed releases remain compatible.

Version 1.10.11 bundles development standard 2.35 and DevKit 1.9.5. Card
creation and submission return a versioned receipt, and `session.context`
exposes up to 20 recent owner-scoped card receipts. Agent code must read the
persisted card by `interaction_id` before treating an answer as submitted;
the client-visible `user_input` remains display text, not proof of a click.
Developer diagnostics include sanitized execution stages for new invocations.

This package is the offline, public development surface for DClaw Super
Agents. It contains the human standard, standalone DevKit, schemas, templates,
SDK helpers, fixtures, and a single cross-platform command line tool. DClaw
server source is not required.

Version 1.10.10 bundles development standard 2.34 and DevKit 1.9.4. Stateful
releases are checked against existing task states before activation. The
activation response includes a state-continuity preflight receipt. Existing
signed packages remain valid.

Version 1.10.9 bundles development standard 2.33 and DevKit 1.9.3. Stateful
releases can sign a `state-contract.json` declaration for complete task-state
continuity across compatible installations. Version 1.10.8 added that new
releases may declare `runtime.failure.read/1` to inspect their own task's last
sanitized failure across installations. The capability is optional and does
not change prior signed releases. See the DevKit runtime-failure schemas.

New projects default to `super_expert_public`: any signed-in DClaw developer can
register a public signing key, upload a verified package, and activate it for
all users without administrator credentials. The private key stays local.
Previously published `super_expert` packages keep their administrator route.
The earlier pack added
stable installation credential slots, restricted HTTPS/WSS streaming outbound,
and temporary resource exchange. Large results move through presigned object
storage and are represented to the Agent by opaque references and digests;
long-term credentials and media bytes remain invisible to the model,
workspace, logs, local helper, and ordinary DClaw API responses. Existing
`credential_ref`, signed Agent, public Component, and local execution contracts
remain compatible. Project upgrades update the pack, standard and DevKit
versions together before validation; no DClaw management page or server source
is required.
Presigned upload creation now has a closed machine response contract, and
streaming HTTPS can safely extract a strict Base64 media field from JSON into
temporary object storage without returning media bytes to the Agent.
Plugin administrators can now upload public Component ZIPs directly to object
storage with `devkit/dclaw_agent_devkit.py component-registry upload`; the
completion receipt must match the signed descriptor used for registration.

## Supported environments

- CPython 3.10 through 3.13
- Windows x64
- macOS x64 and ARM64
- Linux glibc x64 and ARM64
- PowerShell 5.1+ for `bootstrap.ps1`
- POSIX shell for `bootstrap.sh`
- Node.js is not required

## Start here

Run all commands from the unpacked developer pack root.

Prepare the locked offline environment once:

```text
bootstrap.ps1     # Windows PowerShell
./bootstrap.sh    # macOS / Linux
```

Use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on macOS and
Linux for the commands below.

```text
python dclaw_developer.py doctor
python dclaw_developer.py init --target ./my-agent --agent-id my-agent --name "My Agent" --local-helper required
python dclaw_developer.py validate --project ./my-agent
python dclaw_developer.py test --project ./my-agent
python dclaw_developer.py keygen --private-key /secure/dev-private.b64 --public-key /secure/dev-public.b64
python dclaw_developer.py build --project ./my-agent --private-key /secure/dev-private.b64 --public-key /secure/dev-public.b64 --output ./release/my-agent-0.1.0.zip
```

For an Agent whose `local-helper` is `optional` or `required`, add
`--capability-artifact-url https://developer.example/capabilities/package.zip`.
The same `build` command then creates and signs the local capability artifact,
verifies that signature, and builds the sealed Super Expert package. Use the
standalone `capability-build` command when the capability artifact must be
prepared before the Super Expert release.

For a capability with multiple modules, embedded runtimes, FFmpeg, models, or
other locked resources, list files and directories in
`capability-pack/windows-x64/capability-build.json`. Each path is validated,
archived deterministically, and recorded with its size and SHA-256 in the
artifact inventory. To sign an existing ZIP produced by another deterministic
builder, set its build manifest source to `prebuilt`, or pass
`--capability-artifact-file /path/to/artifact.zip`; the CLI validates ZIP paths
and integrity before binding its digest into the signed descriptor.

Every local capability project must also keep
`capability-pack/windows-x64/resources.lock.json` release-ready. The lock fixes
the production HTTPS allowlist and, for every external resource, its size,
SHA-256, SBOM evidence, license evidence, cache key, and rollback version.
`validate`, `test`, `capability-build`, and `build` reject blocked resources,
placeholder hosts such as `.test` or localhost, unapproved domains, temporary
paths, and incomplete evidence before writing an artifact or sealed ZIP.

The project test adapter is declared in `project.json`:

```json
{
  "tests": {
    "adapter": "pytest",
    "paths": ["tests"],
    "arguments": ["-q"]
  }
}
```

Supported adapters are `unittest` and `pytest`. The CLI invokes them without a
shell and writes the normalized command plus the actual executed test count to
release evidence. When project test dependencies live in a project virtual
environment, set `tests.python` to its safe project-relative interpreter path,
which must be exactly `.venv/Scripts/python.exe` or `.venv/bin/python`. The pack verifies the
project virtual environment, CPython version, executable identity and
`sys.prefix`; normal POSIX virtual-environment Python symlinks are supported,
while directory symlink escapes, wrappers and arbitrary interpreters are
rejected. Projects without this field retain unittest discovery with the
interpreter running the developer CLI.

`build` runs the mandatory release gate, project tests, standalone DevKit
validation, sealing, signature verification, and evidence generation. It fails
closed when behavior evidence, approvals, schemas, capability declarations,
dependencies, resource locks, or signing checks are incomplete.

Run the bundled end-to-end exercise without production credentials:

```text
python dclaw_developer.py demo --workspace ./demo-work
```

The exercise copies the example outside the pack, runs its local capability,
generates an ephemeral test signer, builds a sealed Super Expert ZIP, verifies
it, and writes reviewable evidence. It performs no network calls or deployment.

See `standard/super-agent-development-standard-v1.zh-CN.md` for the governing
rules, `COMPATIBILITY.md` for supported versions, and `UPGRADE.md` for upgrades
and rollback.

## Package layout

```text
dclaw-super-agent-developer-pack-<version>/
  dclaw_developer.py
  bootstrap.ps1
  bootstrap.sh
  PACKAGE-MANIFEST.json
  SHA256SUMS
  standard/
  devkit/
    schemas/
    templates/
    wheelhouse/
  schemas/
    developer-pack-v1/
  sdk/python/
  templates/project/
    agent/
    business-service/
    capability-pack/windows-x64/
    docs/
    tests/
  examples/minimal-local/
  SBOM.spdx.json
  THIRD_PARTY_LICENSES.md
  COMPATIBILITY.md
  CHANGELOG.md
  UPGRADE.md
```

## Release workflow

1. Verify the downloaded ZIP against the authenticated metadata SHA-256 and
   verify all entries in `SHA256SUMS`.
2. Bootstrap the offline environment and run `doctor`.
3. Initialize a project. The generated behavior evidence is deliberately a
   draft, so a new project cannot be sealed before real evidence is recorded.
4. Implement the Agent, optional business service, and optional local
   capability. Keep long-lived credentials outside the project and inject them
   into the business service or the approved credential broker.
5. Use DevKit `keygen` and `publish register-signer` with your own signed-in
   DClaw identity, then put the returned signer ID in the manifest. Complete
   `SOURCE_BEHAVIOR_SPEC.json` and
   record every approved behavior difference in `PORTING_RECORD.json`.
6. Run `validate` and `test` until both pass.
7. Keep the Ed25519 private key outside the project and run `build`. Archive the
   generated ZIP, checksum, and `release-evidence/<version>.json`.
8. Use DevKit `publish upload` to verify, grant, activate, and make the new
   public package visible. Run real client tasks and update the version if needed.
   The administrator can disable or delete a nonconforming expert.
