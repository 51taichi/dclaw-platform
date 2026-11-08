# Changelog

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
