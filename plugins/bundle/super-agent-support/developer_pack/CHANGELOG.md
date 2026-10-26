# Changelog

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
