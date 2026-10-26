# Changelog

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
