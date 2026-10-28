# Changelog

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
