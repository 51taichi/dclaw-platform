# Desktop Version Management Design

## Scope

Manage one shared semantic version for the DClaw macOS and Windows desktop applications. The WeChat mini program keeps its independent version. Version changes never create Git commits automatically.

## Source of truth

The repository-root `VERSION` file contains the canonical desktop version as `MAJOR.MINOR.PATCH`. The initial value is `1.1.10`.

## Commands

Commands run from `console/`:

- `npm run version:show` prints the current desktop version and verifies synchronized files.
- `npm run version:patch` increments PATCH.
- `npm run version:minor` increments MINOR and resets PATCH to zero.
- `npm run version:major` increments MAJOR and resets MINOR and PATCH to zero.
- `npm run version:set -- 1.3.5` sets an explicit semantic version.

Every modifying command synchronizes `VERSION`, `console/src-tauri/tauri.conf.json`, and `console/src-tauri/Cargo.toml`. `console/package.json` remains package metadata rather than an application-version source.

## Build safety

The desktop build entry point validates that all synchronized files match `VERSION` before invoking Tauri. A mismatch stops the build with an actionable error. This makes macOS and Windows artifacts use the same version and prevents stale installer names.

## Release policy

Before each requested release build, ask the user whether the release is `patch`, `minor`, or `major`. Do not infer or apply a version bump without their answer.
