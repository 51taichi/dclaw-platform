# Sealed Global Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `0..N` signed, globally callable sealed agents that DClaw users and application administrators can invoke but cannot inspect, edit, clone, export, or download, including through OpenAPI.

**Architecture:** A sealed-agent registry and immutable release store live outside ordinary workspace-serving roots. A centralized backend policy guards every agent-scoped content surface, while a signed-package service validates and activates releases and exposes only public/operational DTOs. The existing conversation runtime and OpenAPI publication flow continue to execute agents, but sealed targets use capability-driven UI, invoke-only publication, and an allowlisted output contract.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, cryptography/Ed25519, pytest; React, TypeScript, Zustand, Vitest, Ant Design-compatible DClaw components.

**Spec:** `docs/superpowers/specs/2026-08-26-sealed-global-agents-design.md`

## Global Constraints

- Sealed agents are optional and have cardinality `0..N`; DClaw startup and standard agents cannot depend on them.
- The first supported combination is `agent_type = sealed` and `scope = global`; do not hard-code `luyu`.
- Customers, tenant administrators, and DClaw system administrators may invoke but never inspect, edit, clone, export, download, or read raw traces for sealed agents.
- Host root and infrastructure operators are outside the confidentiality threat model.
- A sealed agent may be exposed through OpenAPI only as `invoke_only` with a sealed response policy.
- Frontend visibility is not an authorization boundary; direct API calls must be denied by the backend.
- Preserve unrelated existing changes in both repositories.

---

### Task 1: Sealed Registry, Types, and Central Policy

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/__init__.py`
- Create: `src/qwenpaw/app/sealed_agents/models.py`
- Create: `src/qwenpaw/app/sealed_agents/registry.py`
- Create: `src/qwenpaw/app/sealed_agents/policy.py`
- Modify: `src/qwenpaw/config/config.py`
- Modify: `src/qwenpaw/app/routers/agents.py`
- Test: `tests/unit/app/sealed_agents/test_registry.py`
- Test: `tests/unit/app/sealed_agents/test_policy.py`
- Test: `tests/unit/app/test_agents_ordering.py`

**Interfaces:**
- Produces: `SealedAgentRegistry(root: Path)`, `get_sealed_agent_registry()`, `is_sealed_agent(agent_id: str) -> bool`, `assert_sealed_capability(agent_id: str, capability: SealedCapability) -> None`, and public capability fields on `AgentSummary`.
- Consumes: existing `WORKING_DIR`, `AgentProfileRef`, and agent list/config loading.

- [ ] **Step 1: Write failing registry and policy tests**

Cover an empty registry, multiple independently listed agents, invalid registry records being isolated, `invoke`/`public_metadata` allowance, and uniform denial of `inspect`, `edit`, `clone`, `export`, `download`, and `trace`. Assert `AgentSummary` for sealed records contains no `workspace_dir` and returns authoritative capability booleans.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest -q tests/unit/app/sealed_agents tests/unit/app/test_agents_ordering.py`

- [ ] **Step 3: Implement immutable models and atomic JSON registry persistence**

Define `AgentType`, `AgentScope`, `SealedReleaseState`, `SealedCapability`, `SealedAgentRecord`, `SealedReleaseRecord`, `AgentCapabilities`, and public/operational DTOs. Store registry metadata at `${WORKING_DIR}/sealed_agents/registry.json`; write via a same-directory temporary file plus `os.replace`, serialize under a process lock, and treat missing/corrupt data as an empty registry with a logged error rather than a startup failure.

- [ ] **Step 4: Implement centralized asset-first policy**

`assert_sealed_capability` must return normally for non-sealed agents, allow only the two public capabilities for sealed agents, and raise a sanitized `HTTPException(403, "Sealed agent asset access denied")` for every protected capability before any path is resolved.

- [ ] **Step 5: Merge ordinary and sealed agents in list DTOs**

Keep standard summaries backward compatible. For sealed summaries set `agent_type="sealed"`, `scope="global"`, omit `workspace_dir`, expose only public metadata and capabilities, and include availability/version without loading protected workspace files.

- [ ] **Step 6: Run tests and commit**

Run: `pytest -q tests/unit/app/sealed_agents tests/unit/app/test_agents_ordering.py`

Commit: `feat: add sealed agent registry and policy`

### Task 2: Signed Package Validation and Immutable Releases

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/package.py`
- Create: `src/qwenpaw/app/sealed_agents/service.py`
- Create: `src/qwenpaw/app/sealed_agents/signing.py`
- Create: `src/qwenpaw/app/routers/sealed_agents.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/sealed_agents/test_package.py`
- Test: `tests/unit/app/sealed_agents/test_service.py`
- Test: `tests/unit/app/test_sealed_agent_admin.py`

**Interfaces:**
- Consumes: Task 1 registry and models.
- Produces: `compute_package_digest`, `verify_package_signature`, `SealedAgentService.install`, `.activate`, `.disable`, `.list_agents`, `.list_releases`; admin routes under `/api/admin/sealed-agents` with no download or content endpoint.

- [ ] **Step 1: Write failing malicious-archive and signing tests**

Generate ZIPs in memory and test valid Ed25519 signatures plus invalid signature, digest tampering, unknown signer, traversal, absolute path, duplicate normalized path, Unicode collision, symlink, hard link/device mode, excessive file count, excessive expanded size, excessive compression ratio, invalid manifest, unsupported `standard`/non-global combinations, duplicate version, and downgrade.

- [ ] **Step 2: Run package tests and confirm failure**

Run: `pytest -q tests/unit/app/sealed_agents/test_package.py`

- [ ] **Step 3: Implement deterministic digest and signature verification**

Canonicalize UTF-8 NFC relative POSIX paths, reject collisions, sort by encoded path bytes, hash path length/path/file length/file bytes, exclude `signature.json`, and verify Ed25519 signatures using public keys loaded from `${WORKING_DIR}/sealed_agents/trusted_signers.json`. Do not log signature payloads or archive members.

- [ ] **Step 4: Implement bounded safe extraction**

Use explicit constants for maximum upload bytes, members, expanded bytes, compression ratio, and per-file bytes. Reject links and non-regular file modes before extraction; write only beneath a newly created staging directory; canonicalize every destination and remove staging on every failure.

- [ ] **Step 5: Implement immutable release installation and activation**

Move validated content to `${WORKING_DIR}/sealed_agents/releases/{agent_id}/{release_id}` with read-only permissions where supported. Persist state transitions atomically. Register a compatible `AgentProfileRef` pointing at the active private release so the existing runtime can load it, but never expose that path in DTOs. Activation must retain the prior active release on validation/reload failure.

- [ ] **Step 6: Add admin release APIs**

Implement list, detail, upload, activate, enable/disable, and rollback endpoints. Return only public/operational DTOs and sanitized error codes. Ensure no GET route returns a package, file list, manifest internals, or asset bytes.

- [ ] **Step 7: Run tests and commit**

Run: `pytest -q tests/unit/app/sealed_agents/test_package.py tests/unit/app/sealed_agents/test_service.py tests/unit/app/test_sealed_agent_admin.py`

Commit: `feat: publish signed sealed agent releases`

### Task 3: Guard Every Existing Asset Surface

**Files:**
- Modify: `src/qwenpaw/app/agent_context.py`
- Modify: `src/qwenpaw/app/routers/agent_scoped.py`
- Modify: `src/qwenpaw/app/routers/workspace.py`
- Modify: `src/qwenpaw/app/routers/files.py`
- Modify: `src/qwenpaw/app/routers/skills.py`
- Modify: `src/qwenpaw/app/routers/skills_stream.py`
- Modify: `src/qwenpaw/app/routers/config.py`
- Modify: `src/qwenpaw/app/routers/tools.py`
- Modify: `src/qwenpaw/app/routers/backup.py`
- Modify: `src/qwenpaw/app/backup_endpoint_policy.py`
- Modify: `src/qwenpaw/app/routers/agent_stats.py`
- Test: `tests/unit/app/sealed_agents/test_route_guards.py`
- Test: `tests/unit/app/test_backup_endpoint_policy.py`

**Interfaces:**
- Consumes: `assert_sealed_capability` from Task 1.
- Produces: reusable `require_agent_capability(request, capability)` dependency/helper applied before content/path resolution.

- [ ] **Step 1: Inventory and parameterize protected routes in a failing test**

Build a parameter table covering list/read/write/delete workspace files, preview/download, skill list/read/install/export/delete, config read/write, tool list/update, backup/restore, stats/raw chats, runtime debug, and any clone/import/export endpoint. For a sealed `X-Agent-Id`, assert `403`, sanitized detail, and mocked filesystem/config readers not called.

- [ ] **Step 2: Run route-guard tests and confirm representative leaks**

Run: `pytest -q tests/unit/app/sealed_agents/test_route_guards.py`

- [ ] **Step 3: Add a common pre-resolution guard**

Resolve the requested agent ID only from trusted request state/header normalization, call the policy before `load_agent_config`, workspace resolution, or manager lookup, and map each router to the narrow capability it needs. Invocation/chat routes remain allowed; content-management routes do not.

- [ ] **Step 4: Exclude sealed agents from backup, restore, clone, and import conflicts**

Backup selection must reject sealed IDs. Restore/import cannot overwrite or convert sealed identities. Aggregate ordinary backup operations ignore sealed agents instead of reading their paths.

- [ ] **Step 5: Run focused and existing route tests, then commit**

Run: `pytest -q tests/unit/app/sealed_agents/test_route_guards.py tests/unit/app/test_backup_endpoint_policy.py tests/unit/routers tests/unit/app/test_private_skill_access.py`

Commit: `feat: enforce sealed agent asset boundaries`

### Task 4: Runtime Working-Area and Output Protection

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/runtime.py`
- Create: `src/qwenpaw/app/sealed_agents/output_policy.py`
- Modify: `src/qwenpaw/app/multi_agent_manager.py`
- Modify: `src/qwenpaw/app/channels/console/channel.py`
- Modify: `src/qwenpaw/app/artifact_filter.py`
- Modify: `src/qwenpaw/agents/react_agent.py`
- Test: `tests/unit/app/sealed_agents/test_runtime.py`
- Test: `tests/unit/app/sealed_agents/test_output_policy.py`
- Test: `tests/unit/agents/test_skill_runtime_privacy.py`

**Interfaces:**
- Consumes: active private release path and sealed registry status.
- Produces: `SealedRuntimeContext(source_root, session_root)`, `authorize_runtime_path`, `sanitize_sealed_output`, and artifact admission that rejects any source under the sealed root.

- [ ] **Step 1: Write failing path, artifact, and output tests**

Test direct paths, `..`, symlinks, copied attachments, archive attempts, generated session artifacts, canary disclosure, long Base64/hex payloads, protected-text similarity, legitimate Lu Yu domain prose, and sanitized exceptions.

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest -q tests/unit/app/sealed_agents/test_runtime.py tests/unit/app/sealed_agents/test_output_policy.py`

- [ ] **Step 3: Create per-session work areas and restrict model-facing tools**

For sealed agents route uploads and generated files to `${WORKING_DIR}/sealed_sessions/{agent_id}/{session_id}`. Keep the source release read-only and outside model-facing file roots. Disable shell tools for sealed agents in the first release and filter management/export tools from the registered tool set.

- [ ] **Step 4: Enforce artifact provenance**

Canonicalize artifact paths, require them to be regular files inside the current session root, reject links and sealed-source ancestry, limit size/type, and return only opaque download IDs mapped server-side to admitted artifacts.

- [ ] **Step 5: Add conservative output policy and sanitized errors**

Load signer-declared canaries and protected text fingerprints at release activation without exposing them through APIs. Block exact/canary/high-confidence long overlap and suspicious encoded bulk output; do not attempt to block ordinary short domain facts. Emit a stable refusal and structured reason code without matched text.

- [ ] **Step 6: Run privacy/runtime regressions and commit**

Run: `pytest -q tests/unit/app/sealed_agents/test_runtime.py tests/unit/app/sealed_agents/test_output_policy.py tests/unit/agents/test_skill_runtime_privacy.py tests/unit/agents/test_workspace_skill_privacy.py`

Commit: `feat: isolate sealed agent runtime output`

### Task 5: Invoke-only OpenAPI Integration

**Files:**
- Modify: `src/qwenpaw/app/open_api/models.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `src/qwenpaw/app/routers/open_api_admin.py`
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/storage/repos/open_api_repo.py`
- Test: `tests/unit/app/test_open_api_admin.py`
- Test: `tests/unit/app/test_open_api_router.py`
- Test: `tests/unit/app/test_open_api_auth.py`
- Test: `tests/unit/app/sealed_agents/test_open_api_sealed.py`

**Interfaces:**
- Consumes: sealed registry, active/healthy status, output policy.
- Produces: publication fields `allowed_capability="invoke_only"` and `response_policy="sealed"`; allowlisted sealed stream serializer.

- [ ] **Step 1: Write failing publication and stream-contract tests**

Assert sealed targets exist through the registry, force `invoke_only`/`sealed`, reject expert-team publication when any sealed member would expose internal orchestration, ignore/reject caller target overrides, return `503` for absent/disabled/unhealthy targets, and serialize only public stream event types.

- [ ] **Step 2: Run OpenAPI tests and confirm failure**

Run: `pytest -q tests/unit/app/sealed_agents/test_open_api_sealed.py tests/unit/app/test_open_api_admin.py tests/unit/app/test_open_api_router.py`

- [ ] **Step 3: Extend publication persistence compatibly**

Add non-null defaults for standard publications and migrate/create SQLite and SQLAlchemy tables without breaking existing rows. Normalize repository DTOs so old rows read as `allowed_capability="standard"`, `response_policy="standard"`.

- [ ] **Step 4: Enforce server-selected sealed publication policy**

Resolve target type from the backend registry. Never accept a more permissive value from the request. Preserve existing fixed target and bound-user resolution; make runtime availability checks sealed-aware.

- [ ] **Step 5: Allowlist stream and error serialization**

For sealed publications emit only `response.started`, text delta, admitted artifact, completion, and sanitized failure. Suppress tool, handoff, retrieval, path, trace, and internal metadata events before serialization.

- [ ] **Step 6: Run OpenAPI regression suite and commit**

Run: `pytest -q tests/unit/app/test_open_api_admin.py tests/unit/app/test_open_api_router.py tests/unit/app/test_open_api_auth.py tests/unit/app/storage/repos/test_open_api_repo.py tests/unit/app/sealed_agents/test_open_api_sealed.py`

Commit: `feat: expose sealed agents through invoke-only open api`

### Task 6: Frontend Capability Model and Route Protection

**Files (client repository):**
- Modify: `console/src/api/types/agents.ts`
- Modify: `console/src/api/modules/agents.ts`
- Modify: `console/src/stores/agentStore.ts`
- Create: `console/src/utils/agentCapabilities.ts`
- Modify: `console/src/layouts/Sidebar.tsx`
- Modify: `console/src/layouts/AdminLayout/index.tsx`
- Modify: `console/src/layouts/ClientLayout/index.tsx`
- Modify: `console/src/pages/Agent/Workspace/index.tsx`
- Modify: `console/src/pages/Agent/Skills/index.tsx`
- Modify: `console/src/pages/Agent/Config/index.tsx`
- Modify: `console/src/pages/Agent/Tools/index.tsx`
- Test: `console/src/utils/agentCapabilities.test.ts`
- Test: `console/src/layouts/ClientLayout.test.tsx`
- Test: relevant page route tests

**Interfaces:**
- Consumes: backend `AgentSummary.capabilities`, `agent_type`, `scope`, `version`, `availability`.
- Produces: `isSealedAgent`, `canManageAgentAsset`, and centralized menu/route decisions.

- [ ] **Step 1: Write failing capability and routing tests**

Test standard backward compatibility, sealed capability parsing, hidden Workspace/Skills/Config/Tools/clone/export/download entries, safe redirect for direct URLs, and visible chat/discovery invocation.

- [ ] **Step 2: Run focused frontend tests and confirm failure**

Run from `console`: `npm test -- --run src/utils/agentCapabilities.test.ts src/layouts/ClientLayout.test.tsx`

- [ ] **Step 3: Add authoritative capability types and selectors**

Make `workspace_dir` optional, preserve standard defaults, and derive UI only from backend capabilities. Do not use an `agent.id === "luyu"` condition.

- [ ] **Step 4: Protect menus and routes**

Hide protected entries for sealed agents and redirect direct protected navigation to the sealed detail route. Keep client invocation and AgentSelector behavior intact.

- [ ] **Step 5: Run frontend tests and commit in client repository**

Run from `console`: `npm test -- --run src/utils/agentCapabilities.test.ts src/layouts/ClientLayout.test.tsx src/stores/agentStore.test.ts`

Commit: `feat: enforce sealed agent ui capabilities`

### Task 7: Frontend Sealed Release and OpenAPI UX

**Files (client repository):**
- Create: `console/src/api/types/sealedAgents.ts`
- Create: `console/src/api/modules/sealedAgents.ts`
- Create: `console/src/pages/Settings/SealedAgents/index.tsx`
- Create: `console/src/pages/Settings/SealedAgents/index.module.less`
- Create: `console/src/pages/Settings/SealedAgents/SealedAgents.test.tsx`
- Modify: `console/src/api/index.ts`
- Modify: `console/src/pages/Settings/OpenApi/index.tsx`
- Modify: `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/components/ChatToolbar.tsx`
- Modify: `console/src/pages/Chat/components/RuntimeProgressCard.tsx`
- Modify: `console/src/layouts/Sidebar.tsx`

**Interfaces:**
- Consumes: sealed admin list/upload/activate/disable/rollback APIs and sealed OpenAPI DTOs.
- Produces: one-way release UI, sealed operational detail, locked OpenAPI policy presentation, and sealed-safe chat rendering.

- [ ] **Step 1: Write failing page behavior tests**

Test empty `0` state, multiple records, signed ZIP upload, public-only preview, sanitized progress/errors, version activation/rollback/disable, absence of content/download actions, locked invoke-only OpenAPI fields, and hidden skill/tool/source/debug chat controls.

- [ ] **Step 2: Run focused tests and confirm failure**

Run from `console`: `npm test -- --run src/pages/Settings/SealedAgents/SealedAgents.test.tsx src/pages/Settings/OpenApi/OpenApi.test.tsx`

- [ ] **Step 3: Implement typed API module and release page**

Use multipart upload without browser-side ZIP extraction. Render only backend DTOs and sanitized phase codes. Provide upload, test invocation, activate, disable, rollback, and OpenAPI navigation; do not add inspect, edit, diff, clone, export, or download actions.

- [ ] **Step 4: Implement sealed OpenAPI and chat presentation**

Lock capability/response fields for sealed targets, retain quota/key controls, and hide internal runtime surfaces in chat while preserving final text and admitted artifacts.

- [ ] **Step 5: Run page and build verification, then commit**

Run from `console`: `npm test -- --run src/pages/Settings/SealedAgents/SealedAgents.test.tsx src/pages/Settings/OpenApi/OpenApi.test.tsx src/pages/Chat/ChatPage.test.tsx`

Run from `console`: `npm run build`

Commit: `feat: add sealed agent release console`

### Task 8: Security Evaluation, Documentation, and Full Verification

**Files:**
- Create: `tests/security/test_sealed_agent_exfiltration.py`
- Create: `docs/sealed-agents.md`
- Modify: `SECURITY.md`
- Modify: the API documentation describing agent/OpenAPI publication contracts
- Test: all suites named below

**Interfaces:**
- Consumes: all previous tasks.
- Produces: documented package/release procedure, threat boundary, signing command, security regression corpus, and final evidence.

- [ ] **Step 1: Add a deterministic signing CLI or script and documented example**

Provide a command that takes a package directory, signer ID, and external private-key path, creates the canonical digest/signature, and writes the final ZIP. Ensure private keys are never copied into the repository or package.

- [ ] **Step 2: Add adversarial security tests**

Cover direct prompt extraction, role impersonation, translation/re-encoding, directory/tool enumeration, ZIP/Base64/external-link requests, indirect injection, multi-turn fragments, OpenAPI stream/error probing, alternate version access, and direct protected API access. Tests assert absence of package canaries and protected source fragments, not merely a verbal refusal.

- [ ] **Step 3: Document operations and threat boundaries**

Document optional `0..N` behavior, trusted signer configuration, publishing, activation, rollback, disablement, OpenAPI invoke-only publication, sanitized auditing, recovery, and the explicit root/infrastructure exclusion.

- [ ] **Step 4: Run backend focused security and regression suites**

Run: `pytest -q tests/unit/app/sealed_agents tests/security/test_sealed_agent_exfiltration.py tests/unit/app/test_agent_package_import.py tests/unit/app/test_open_api_admin.py tests/unit/app/test_open_api_router.py tests/unit/app/test_open_api_auth.py tests/unit/app/test_backup_endpoint_policy.py tests/unit/app/test_private_skill_access.py`

- [ ] **Step 5: Run backend quality checks**

Run the repository's configured formatter/linter/type-check commands discovered from `pyproject.toml` and CI configuration. Then run the broadest practical backend test suite; any excluded integration suite must be listed with the missing external dependency.

- [ ] **Step 6: Run frontend full verification**

From `/Users/moxi/Desktop/codex space/dclaw-client/console`, run `npm test -- --run`, `npm run build`, and the configured lint/type-check commands.

- [ ] **Step 7: Perform completion audit against every acceptance criterion**

Map each of the ten spec acceptance criteria to source code plus passing test/runtime evidence. Search both repositories for hard-coded `luyu`, exposed sealed paths, package download routes, and frontend-only authorization. Fix every gap before declaring completion.

- [ ] **Step 8: Commit final tests and documentation**

Commit: `test: verify sealed agent confidentiality`
