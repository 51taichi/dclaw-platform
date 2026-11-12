# DClaw Super Agent Developer Pack

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
