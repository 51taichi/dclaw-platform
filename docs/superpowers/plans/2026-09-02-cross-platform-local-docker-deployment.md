# DClaw Cross-Platform Local Docker Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, run, operate, and verify the current DClaw and Luyu source as one LAN-accessible Docker deployment on macOS, reusable on Windows and Linux.

**Architecture:** A cross-platform Python deployment CLI owns validation and orchestration, while thin shell and PowerShell launchers provide native entrypoints. A dedicated Compose file runs DClaw, PostgreSQL, and Redis with stable production names and volumes; a temporary context assembler combines the two source repositories for the existing multi-stage Dockerfile.

**Tech Stack:** Docker Desktop, Docker Compose v2/v5, Python 3.10+, Bash, PowerShell 7, PostgreSQL 16, Redis 7, FastAPI/Vite application image.

**Spec:** `docs/superpowers/specs/2026-09-02-cross-platform-local-docker-deployment-design.md`

## Global Constraints

- Compose project name is `dclaw-production`.
- LAN bind defaults to `0.0.0.0:18088`; PostgreSQL and Redis expose no host ports.
- Authentication defaults enabled and secrets never enter the image or tracked files.
- The image is built from the current server and client working trees.
- Luyu is installed only through its signed super-expert release flow.
- macOS, Windows, and Linux share one Compose definition and one Python implementation.

---

### Task 1: Deployment contracts and environment validation

**Files:**
- Create: `deploy/local/compose.local.yml`
- Create: `deploy/local/local.env.example`
- Create: `deploy/local/deploy.py`
- Create: `tests/unit/deploy/test_local_deploy.py`

**Interfaces:**
- Produces: `DeploymentConfig.from_environment(root: Path)`, `validate_environment(config)`, and CLI subcommands.

- [ ] Write tests for stable names, private database/Redis networking, LAN bind, required secret validation, redacted diagnostics, and platform-independent paths.
- [ ] Run `pytest -q tests/unit/deploy/test_local_deploy.py`; expect failure because deployment modules do not exist.
- [ ] Implement strict config parsing and the Compose/environment templates.
- [ ] Re-run the focused tests; expect PASS.

### Task 2: Current-source build context and immutable image

**Files:**
- Modify: `deploy/local/deploy.py`
- Test: `tests/unit/deploy/test_local_deploy.py`

**Interfaces:**
- Produces: `assemble_build_context(config, target)`, `source_identity(path)`, and `build_image(config)`.

- [ ] Add failing tests proving server/client files are assembled without modifying either source tree, excluded development artifacts are not copied, and dirty-tree fingerprints affect the tag.
- [ ] Implement temporary context assembly and Docker label/tag generation.
- [ ] Run focused tests and a Docker build on `linux/arm64`; expect PASS.

### Task 3: Lifecycle, health, LAN and persistence commands

**Files:**
- Modify: `deploy/local/deploy.py`
- Create: `deploy/local/dclaw-local.sh`
- Create: `deploy/local/dclaw-local.ps1`
- Test: `tests/unit/deploy/test_local_deploy.py`

**Interfaces:**
- Produces CLI commands `init`, `build`, `start`, `stop`, `restart`, `status`, `logs`, and `doctor`.

- [ ] Add command-construction tests that assert fixed project name, explicit env/Compose paths, safe subprocess arguments, health timeout, and secret redaction.
- [ ] Implement lifecycle commands and thin platform launchers.
- [ ] Run tests, initialize a real local environment, start the stack, and verify all health checks.

### Task 4: Verified backup, restore, upgrade and rollback

**Files:**
- Modify: `deploy/local/deploy.py`
- Test: `tests/unit/deploy/test_local_deploy.py`

**Interfaces:**
- Produces CLI commands `backup`, `restore`, `upgrade`, and `rollback` plus a versioned backup manifest.

- [ ] Add failing tests for atomic backup directories, PostgreSQL dump verification, archive verification, manifest checksums, mandatory pre-upgrade backup, and incompatible restore rejection.
- [ ] Implement backup/restore and image rollback without printing secrets.
- [ ] Test against the running local stack, including restore into a temporary validation project.

### Task 5: Signed Luyu installation and activation

**Files:**
- Modify: `deploy/local/deploy.py`
- Create: `deploy/local/install_luyu.py`
- Test: `tests/unit/deploy/test_local_luyu_install.py`

**Interfaces:**
- Produces CLI command `install-luyu` and a sanitized installation receipt.

- [ ] Add failing tests for release-manifest drift, missing official key, install/grant/activate failure, partial grant rejection, and idempotent same-release detection.
- [ ] Implement signed package build and standard DClaw administrative installation calls; never mount Luyu source into the running app.
- [ ] Install the actual current Luyu package, verify complete capability grant, activate it, and run a fresh-session orchestration smoke test.

### Task 6: End-to-end acceptance and operator guide

**Files:**
- Create: `deploy/local/README.md`
- Create: `tests/integration/test_local_deployment_contract.py`
- Modify: `docs/superpowers/plans/2026-09-02-cross-platform-local-docker-deployment.md`

**Interfaces:**
- Produces: reproducible Mac acceptance evidence and Windows migration instructions.

- [ ] Test local and LAN HTTP access, authentication, container recreation persistence, model-provider readiness, Luyu runtime traces, unauthorized denial, and the card/AIGC review loop.
- [ ] Run backup and restore validation, then restart Docker services and repeat health/persistence checks.
- [ ] Document exact Mac and Windows commands, firewall scope, data locations, recovery steps, and current image/source identities.
- [ ] Run server focused tests, client full tests/build, Luyu full tests/manifest verification, and deployment tests; require no deployment-caused regression.
- [ ] Record final container/image/volume status without secrets and commit the deployment deliverables.
