# Desktop Version Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, centralized semantic-version management for DClaw macOS and Windows desktop builds.

**Architecture:** A repository-root `VERSION` file is the only human-edited desktop version source. A focused Node module reads, validates, increments, synchronizes, and checks the version; a small CLI exposes these operations, and the existing desktop build script blocks builds when configuration is inconsistent.

**Tech Stack:** Node.js ESM, Node test runner, JSON, Cargo TOML, Tauri 2

**Spec:** `docs/superpowers/specs/2026-08-30-desktop-version-management-design.md`

## Global Constraints

- macOS and Windows share one `MAJOR.MINOR.PATCH` desktop version.
- The WeChat mini program version remains independent.
- Version commands never commit to Git.
- A release bump is selected by the user as `patch`, `minor`, or `major` before packaging.

---

### Task 1: Version Library and CLI

**Files:**
- Create: `VERSION`
- Create: `console/scripts/desktop-version.mjs`
- Create: `console/scripts/desktop-version-cli.mjs`
- Create: `console/scripts/desktop-version.test.mjs`
- Modify: `console/package.json`
- Modify: `console/package-lock.json`

**Interfaces:**
- Produces: `readCanonicalVersion()`, `assertVersionsSynchronized()`, `setDesktopVersion(version)`, and `incrementVersion(version, releaseType)`.
- Produces CLI actions `show`, `patch`, `minor`, `major`, and `set`.

- [ ] **Step 1: Write failing unit tests**

Test valid SemVer parsing, invalid versions, patch/minor/major increments, mismatch reporting, and synchronization in a temporary fixture.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test scripts/desktop-version.test.mjs`

Expected: failure because `desktop-version.mjs` does not exist.

- [ ] **Step 3: Implement the minimal version module and CLI**

Use exact JSON parsing for Tauri configuration and a narrowly scoped Cargo package-version replacement. Write files only after all inputs validate.

- [ ] **Step 4: Add npm command aliases and refresh the npm lockfile**

Add `version:show`, `version:patch`, `version:minor`, `version:major`, and `version:set` scripts.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `node --test scripts/desktop-version.test.mjs`

Expected: all tests pass.

### Task 2: Build-Time Version Guard

**Files:**
- Modify: `console/scripts/build-desktop.mjs`
- Modify: `console/scripts/build-desktop.test.mjs`

**Interfaces:**
- Consumes: `assertVersionsSynchronized()` from Task 1.
- Produces: desktop builds that exit nonzero before Tauri starts if versions differ.

- [ ] **Step 1: Write a failing build-guard test**

Add an injectable check mode that demonstrates a mismatched fixture is rejected without running Tauri.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test scripts/build-desktop.test.mjs`

Expected: failure because build-time synchronization checking is absent.

- [ ] **Step 3: Invoke the synchronization guard before build execution**

Keep `--describe` side-effect free and validate the real project for normal builds.

- [ ] **Step 4: Run focused and aggregate tests**

Run: `node --test scripts/desktop-version.test.mjs scripts/build-desktop.test.mjs`

Expected: all tests pass.

### Task 3: End-to-End Verification

**Files:**
- Verify only; no new files.

**Interfaces:**
- Consumes all commands and guards from Tasks 1 and 2.
- Produces evidence that version state and application compilation are valid.

- [ ] **Step 1: Verify current synchronization**

Run: `npm run version:show`

Expected: `1.1.10` and exit code zero.

- [ ] **Step 2: Verify frontend checks**

Run: `npm run format:check`

Expected: exit code zero.

- [ ] **Step 3: Verify Rust metadata**

Run: `cargo check --locked --manifest-path src-tauri/Cargo.toml`

Expected: exit code zero.

- [ ] **Step 4: Review the final diff without committing**

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors; existing user changes remain present and no commit is created.
