# Changelog

## 1.10.48 - 2026-11-27

- Bundle standard 2.69 and DevKit 1.9.33 for single-call model-first card
  suggestions, nonblocking text entry, custom choice counting and fallback.
- Preserve signed legacy releases and their existing interaction policies.

## 1.10.47 - 2026-11-26

- Bundle standard 2.68 and DevKit 1.9.32 with the closed `agent.execute` v2
  contract and reference calls.
- Default new v2 releases to the governed Agent Loop while preserving the v1
  candidate default and requiring explicit `candidate` for v2 model-only JSON.

## 1.10.46 - 2026-11-20

- Bundle standard 2.67 and DevKit 1.9.31 with backward-compatible workspace
  continuation for schema-compatible state from retired Releases.
- Keep the five-version rollback list while ignoring unbound legacy auxiliary
  JSON and preflighting retired-source state before activation.

## 1.10.45 - 2026-11-19

- Bundle standard 2.66 and DevKit 1.9.31 with model route preflight and
  content-free model/Agent timeout diagnostics in Support 1.18.56.
- Preserve explicit chat model selection and automatic routing; retired fixed
  declarations require a supported model before the expert runtime starts.

## 1.10.44 - 2026-11-17

- Bundle standard 2.65 and DevKit 1.9.31 with closed `agent.execute` and
  `runtime.fail` schemas, strict API demos, and failed-turn card compensation.
- Preserve valid legacy calls and activated releases; new releases can validate
  candidate, JSON and tool-loop modes without permissive fake Host behavior.

## 1.10.43 - 2026-11-17

- Bundle standard 2.64 and DevKit 1.9.30 with owner-scoped runtime diagnostics
  v6, combining retained Host and Helper task evidence by invocation ID.
- Generic Host exceptions record only a stable observed failure; v5 and Agent
  business behavior remain unchanged.

## 1.10.42 - 2026-11-17

- Bundle standard 2.63 and DevKit 1.9.29. Support plugin 1.18.53 verifies the
  public runtime worker and isolation probe instead of accepting a live socket
  as sufficient health evidence.
- Diagnostics v5 maps only the recorded, allowlisted runtime isolation failure
  to a stable platform blocker. Unknown internal diagnostic text stays hidden.

## 1.10.41 - 2026-11-16

- Bundle standard 2.62 and DevKit 1.9.29 with owner-scoped local task
  diagnostics v2 for all local capabilities. Historical exception types are
  mapped only when safely recorded; missing stages remain explicit.
- Support plugin 1.18.52 publishes Helper 1.4.12, which records safe failure
  stages for task start and continuation. The v1 localization API is unchanged.

## 1.10.40 - 2026-11-16

- Bundle standard 2.61 and DevKit 1.9.28 with `plan_version=2` complete-file
  video timeline schemas, example and API demo. Version 1 trim inputs remain
  valid; Support plugin 1.18.50 and Helper 1.4.10 gate version 2.

## 1.10.39 - 2026-11-16

- Bundle standard 2.60 and DevKit 1.9.27 with the closed Helper bind-result
  message schema. Support plugin 1.18.49 consumes the result and bounds the
  device wait; no Agent request or Helper binary update is required.

## 1.10.38 - 2026-11-16

- Bundle standard 2.59 and DevKit 1.9.26 with the shared structured video
  timeline render task. Helper 1.4.9 generates FFmpeg arguments locally.
- Replace the unshipped `dclaw.ffmpeg.command` raw argument demo; new Agents
  must use `dclaw.ffmpeg.task.plan` and trusted file bindings.

## 1.10.37 - 2026-11-16

- Bundle standard 2.58 and DevKit 1.9.25 with the platform-owned
  `dclaw.ffmpeg.command` built-in task input/result Schemas and API demo.
  Existing Host task contracts remain compatible; Helper 1.4.8 is required.

## 1.10.36 - 2026-11-15

- Fix `required` local Helper validation to accept published `local_execution`
  capabilities such as `local.runtime.prepare/1`. Unknown capabilities remain
  rejected. Standard 2.57, DevKit 1.9.24, and Helper 1.4.7 are unchanged.

## 1.10.35 - 2026-11-15

- Bundles standard 2.57 and DevKit 1.9.24 with the sealed Host
  `local.runtime.prepare/1` request/response schemas and API demo.

## 1.10.34 - 2026-11-15

- Bundles standard 2.56 and DevKit 1.9.23 with a sealed Host API demo and
  closed schemas for verified prior localization files used in a later task.

## 1.10.33 - 2026-11-15

- Bundles standard 2.55 and DevKit 1.9.22 with owner-scoped, redacted local
  task diagnostics and the Helper 1.4.6 AIGC localization requirement.

## 1.10.32 - 2026-11-14

- Bundles standard 2.54 and DevKit 1.9.21. The shared AIGC localization Host
  uses stable public OSS URLs after an owner-scoped selection and unauthenticated
  readability check; Agent request and receipt schemas remain unchanged.

## 1.10.31 - 2026-11-14

- Bundles standard 2.53 and DevKit 1.9.20 with node-by-node localization
  acceptance criteria and the Host diagnostic fallback.

## 1.10.30 - 2026-11-14

- Bundles standard 2.52 and DevKit 1.9.20 with owner-scoped, redacted
  AIGC localization Host blocker diagnostics and a versioned API example.

## 1.10.29 - 2026-11-13

- Bundles standard 2.51 and DevKit 1.9.19 with owner-scoped diagnostics for
  completed business-blocked turns and redacted Host operation receipts.

## 1.10.28 - 2026-11-13

- Bundles standard 2.50 and DevKit 1.9.18 with the optional, owner-scoped
  AIGC task binding recovery Host contract and closed schemas.

## 1.10.27 - 2026-11-12

- Bundles development standard 2.49 and DevKit 1.9.17.
- Makes customer completion unambiguous to legacy signed AIGC instructions
  without claiming that Agent review was performed.

## 1.10.26 - 2026-11-12

- Bundles development standard 2.48 and DevKit 1.9.16.
- Documents the read-only compatibility tool for already signed Agents while
  keeping customer completion as the only acceptance path for new work.

## 1.10.25 - 2026-11-12

- Bundles development standard 2.47 and DevKit 1.9.15.
- Documents direct customer completion of owned AIGC tasks without Agent
  review or an Agent-declared submit grant. Legacy capability IDs and history
  remain readable, while new Agent/Host submit and review writes are retired.

## 1.10.24 - 2026-11-12

- Bundles development standard 2.46 and DevKit 1.9.14.
- Documents the canonical AIGC asset listing, selection and Local Helper
  delivery flow, including minimum versions and legacy digest semantics.

## 1.10.23 - 2026-11-12

- Bundles development standard 2.45 and DevKit 1.9.14.
- Adds task-bound AIGC asset listing and Local Helper delivery contracts while
  keeping signed download URLs outside Agent-visible and persisted payloads.

## 1.10.22 - 2026-11-11

- Accepts cataloged optional `local.task.*` Host capabilities when a project
  requires the local helper, while preserving mandatory local declarations.

## 1.10.21 - 2026-11-11

- Bundles development standard 2.45 and DevKit 1.9.13.
- Adds owner-scoped Host rejection diagnostics v3 and bounded failure-reference
  search without changing v1/v2 responses or existing signed Agent contracts.

## 1.10.20 - 2026-11-10

- Bundles development standard 2.44 and DevKit 1.9.12.
- Adds runnable AIGC workflow/task-card and local-helper task API references
  with live catalog, scoped receipt, retry and terminal-asset examples.

## 1.10.19 - 2026-11-10

- Bundles development standard 2.43 and DevKit 1.9.11.
- Adds a runnable direct Host API reference and contract regression for the
  shared card create and trusted receipt flow.

## 1.10.18 - 2026-11-10

- Bundles development standard 2.42 and DevKit 1.9.10.
- Adds the complete live `single_select` catalog snapshot, full Draft 2020-12
  validation reference, and positive and negative card tests.

## 1.10.17 - 2026-11-09

- Bundles development standard 2.41 and DevKit 1.9.9.
- Adds direct Host interaction catalog/create schemas and a validated
  `single_select` success example, including idempotency and receipt linkage.

## 1.10.16 - 2026-11-09

- Bundles development standard 2.40 and DevKit 1.9.8.
- Documents the two-stage internal text and card-draft flow, followed by
  validated Host card creation. Existing signed Agent tool paths remain valid.

## 1.10.15 - 2026-11-09

- Bundles development standard 2.39 and DevKit 1.9.8.
- Documents final-blocker diagnostics v2, Agent-loop model defaults, and the existing trusted card, AIGC, and local task receipts.

## 1.10.14 - 2026-11-08

- Bundles development standard 2.38 and DevKit 1.9.7.
- Adds owner-scoped reference diagnostics, bound AIGC asset snapshots, and
  deterministic local-task Host receipts. Existing signed Agents keep their
  prior capabilities and contracts.

## 1.10.13 - 2026-11-07

- Bundles development standard 2.37 and DevKit 1.9.6.
- Makes plugin interface stability, active-release impact assessment, and
  coordinated updates of affected signed Agents explicit release gates.

## 1.10.12 - 2026-11-07

- Bundles development standard 2.36 and DevKit 1.9.6.
- Adds the optional, scoped `interaction.card.read/1` contract without changing
  existing interaction capabilities or signed packages.

## 1.10.11 - 2026-11-07

- Bundles development standard 2.35 and DevKit 1.9.5.
- Adds closed interaction card receipt schemas and sanitized per-invocation
  execution stages; older signed packages and card responses remain compatible.

## 1.10.10 - 2026-11-06

- Bundles development standard 2.34 and DevKit 1.9.4.
- Documents activation preflight for existing task states and its publication
  receipt; internal model candidates stay out of chat history.

## 1.10.9 - 2026-11-06

- Bundles development standard 2.33 and DevKit 1.9.3.
- Adds signed workspace state continuity declarations and fail-closed upgrade rules.

## 1.10.8 - 2026-11-06

- Bundles development standard 2.32 and DevKit 1.9.2.
- Documents preservation of prior Agent memory when a runtime turn fails.

## 1.10.7 - 2026-11-06

- Bundles development standard 2.31 and DevKit 1.9.2.
- Excludes mutable Python caches from signed Agent builds and documents
  owner-scoped startup failure diagnostics.

## 1.10.6 - 2026-11-05

- Bundles development standard 2.30 and DevKit 1.9.1.
- Adds optional owner-scoped `runtime.failure.read/1` across installations,
  with closed schemas and a 30-day read window.
- Documents the existing `agent.execute` JSON object request boundary.

## 1.10.5 - 2026-11-05

- Bundles development standard 2.29 and DevKit 1.9.0.
- Documents fail-closed state filename bindings for migrated tasks.

## 1.10.4 - 2026-11-05

- Bundles development standard 2.28 and DevKit 1.9.0.
- Documents target state filenames for platform-managed installation migration.

## 1.10.3 - 2026-11-05

- Bundles development standard 2.27 and DevKit 1.9.0.
- Documents stable parent-directory mounts for the public runtime sidecar
  across support-plugin hot updates.

## 1.10.2 - 2026-11-05

- Bundles development standard 2.26 and DevKit 1.9.0.
- Documents explicit empty-target initialization for operator-controlled
  cross-installation state recovery; Agent runtime contracts are unchanged.

## 1.10.1 - 2026-11-04

- Bundles development standard 2.25 and DevKit 1.9.0.
- Documents the plugin operator's versioned cross-installation state restore
  contract; Agent runtime and signing formats remain unchanged.

## 1.10.0 - 2026-11-03

- Bundles development standard 2.24 and DevKit 1.9.0.
- Adds ordinary-user public signer registration and owner-scoped upload,
  grant, activation, and globally visible testing for `super_expert_public`.
- Keeps official `super_expert` packages and administrator publication intact.

## 1.9.3 - 2026-11-02

- Bundles development standard 2.23 and DevKit 1.8.3.
- Moves the Windows local-helper binary and version manifest into the support
  plugin release, with authenticated on-demand download and atomic updates.
- Replaces Runner upgrade guidance that required a DClaw client release with
  the plugin-managed `update_local_helper` action.

## 1.9.2 - 2026-11-02

- Bundles development standard 2.22 and DevKit 1.8.2.
- Adds administrator-only direct object-storage upload for public Components,
  completion verification, and a receipt binding before signed registration.
- Keeps existing external HTTPS Components and signed Agents compatible.

## 1.9.1 - 2026-10-31

- Bundles development standard 2.21 and DevKit 1.8.1.
- Publishes the closed presigned-upload creation response contract.
- Adds a bounded, provider-neutral JSON Pointer plus strict Base64 response
  transform for HTTPS media responses without exposing media bytes to Agents.
- Keeps pack 1.9.0, DevKit 1.8.0, existing signed Agents, and contract version 1
  callers compatible.

## 1.9.0 - 2026-10-31

- Bundles development standard 2.20 and DevKit 1.8.0.
- Adds stable installation credential slots while retaining legacy opaque
  credential references for existing signed Agents.
- Publishes bounded HTTPS/WSS outbound and temporary resource exchange
  contracts; local helper transfers use presigned object storage and media
  bytes never enter the Agent or ordinary DClaw API response.
- Keeps existing signed package, local execution, public Component, business
  service identity, and `agent.outbound/1` contracts compatible.

## 1.8.0 - 2026-10-30

- Bundles development standard 2.19 and DevKit 1.7.0.
- Publishes `agent.outbound/1` for Agent-owned third-party HTTP calls with
  installation-scoped encrypted credential references.
- Keeps provider choice, request parameters, polling, retries, fees, and
  response interpretation in the sealed Agent; the local helper receives no
  third-party long-term key.
- Retains all existing signed package, local execution, public Component, and
  business-service identity contracts for compatibility.

## 1.7.0 - 2026-10-28

- Bundles development standard 2.14 and DevKit 1.6.0.
- Adds explicit non-entry public Component export bindings for Runner 1.3.0.
- Keeps capability descriptors without `component_exports` compatible with
  existing Runner requirements.

## 1.6.1 - 2026-10-28

- Bundles development standard 2.13 and DevKit 1.5.0.
- Requires legacy Agent runtimes to be mapped into the public Component registry before any separate cleanup decision.

## 1.6.0 - 2026-10-28

- Bundles development standard 2.12 and DevKit 1.5.0.
- Adds the signed public Component descriptor and exact dependency declarations.
- Adds the headless authenticated `component-registry get/register` workflow.
- Keeps existing signed Agent packages and capability descriptors without
  `public_components` compatible.

## 1.5.4 - 2026-10-28

- Bundles development standard 2.11 and keeps DevKit 1.4.1.
- Defines public Component management as a headless, versioned support-plugin
  API/CLI called by the migration Skill and platform maintenance automation.
- Keeps DClaw core, client pages, administration pages, and existing signed
  Agent machine contracts unchanged.

## 1.5.3 - 2026-10-28

- Bundles development standard 2.10 and keeps DevKit 1.4.1.
- Clarifies that reusable local components for Super Agents are owned and
  released by `dclaw.super-agent-support`; Agent projects only declare and
  adapt to registered versions.
- Keeps sealed Agent, capability package, local execution, and business
  identity machine contracts unchanged.

## 1.5.2 - 2026-10-27

- Fixes `upgrade --project` to update `project.json.devkit_version` together
  with the developer pack and standard versions.
- Records the previous DevKit version and requires immediate validation of the
  upgraded project metadata.
- Bundles development standard 2.9 and its authenticated, immutable shared
  toolchain release process.
- Keeps DevKit 1.4.1 and every public manifest, signature, local execution and
  business identity contract unchanged.

## 1.5.1 - 2026-10-27

- Publishes DevKit 1.4.1 and development standard 2.8 with the exact MCP
  operation catalog and controlled outbound assertion transport contract.
- Supports standard POSIX project virtual-environment Python symlinks after
  validating the interpreter, project environment and `sys.prefix`.
- Rejects directory symlink escapes, wrappers, arbitrary interpreters,
  Agent-supplied authorization and case-insensitive duplicate headers.
- Excludes AppleDouble, Finder, bytecode and macOS archive metadata from
  deterministic Developer Pack and DevKit downloads.
- Documents anonymous cached JWK discovery and keeps existing signed Agent,
  manifest, local execution and business identity contract versions valid.

## 1.5.0 - 2026-10-27

- Publishes DevKit 1.4.0 and the strict installation-bound business service
  identity schemas for issue, controlled outbound transport, verification,
  administration, and stable errors.
- Declares `business.service.installation-identity/1` as a server-side platform
  capability with no Runner dependency.
- Bundles the single human development standard 2.7; no parallel standard is
  introduced.
- Retains the release-ready resource lock and secret-scan fixes introduced in
  1.4.1.

## 1.4.1 - 2026-10-27

- Validates `resources.lock.json` before writing a capability artifact or
  sealed Super Expert ZIP.
- Fails closed for blocked resources, non-production or unapproved URLs,
  missing sizes or SHA-256 digests, incomplete SBOM or license evidence,
  missing cache keys, and missing rollback versions.
- Bundles development standard 2.6 while keeping DevKit 1.3.0 and all existing
  signed descriptor and manifest contracts compatible.

## 1.4.0 - 2026-10-26

- Bundles development standard 2.5 and its mandatory core-residue audit.
- Keeps every Super Agent-only implementation in the support plugin while
  retaining thin historical Python import paths for existing signed Agents.
- Keeps DevKit 1.3.0 and all signed package and local execution contracts
  compatible.

## 1.3.0 - 2026-10-26

- Bundles development standard 2.4 with the explicit Super Agent plugin
  ownership boundary and fail-closed release prerequisites.
- Clarifies signer trust domains, business service installation identity, and
  the split between the generic Runner core and Agent capability packages.
- Keeps DevKit 1.3.0 schemas and all existing signed package formats compatible.

## 1.2.0 - 2026-10-26

- Bundles DevKit 1.3.0 public contracts for opaque local file references,
  read-only task bindings, direct device uploads, and managed artifacts.
- Allows an awaiting task to receive additional read-only file bindings through
  `local_task_continue` while preserving its task and checkpoint identity.
- Keeps the existing sealing format and local execution 1.0 path compatible;
  file workflows require local execution 1.1 and Runner 1.1.0.

## 1.1.0 - 2026-10-26

- Adds the versioned `capability-build.json` contract for deterministic
  capability artifacts containing arbitrary files, directories, runtimes, and
  locked dependencies.
- Adds safe import of a prebuilt capability ZIP through the build manifest or
  `--artifact-file`, followed by digest binding and descriptor signing.
- Adds controlled `unittest` and `pytest` adapters in `project.json`; release
  evidence now records the adapter, normalized command, and actual test count.
- Keeps the 1.0 defaults when an upgraded project omits the new declarations.

## 1.0.0 - 2026-10-26

- First offline developer pack for development standard 2.1.
- Bundles the standalone Super Agent DevKit 1.2.0 and its locked wheelhouse.
- Adds project initialization, environment checks, validation, tests, sealing,
  verification, upgrade metadata, and a complete offline demonstration.
- Builds and signs local capability artifacts and descriptors when local helper
  execution is declared, then verifies them with the release public key.
- Adds mandatory behavior baseline, approved-difference, capability, dependency,
  secret-scan, test, and signature release gates.
- Adds public business service and local capability templates without server
  source dependencies.
