# Super Expert Harness Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show two disabled Harness switches for each active super expert, with values projected from that expert's current effective configuration.

**Architecture:** DClaw Server validates the active runtime workspace configuration and returns only two nullable booleans in the sealed-agent operational DTO. DClaw Console renders those booleans as disabled switches. The LuYu package adds an explicit Agent Loop declaration so the display never infers state from `runtime.py` source.

**Tech Stack:** Python 3.10+, Pydantic, FastAPI, pytest, React 18, TypeScript, Ant Design, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-11-super-expert-harness-status-design.md`

## Global Constraints

- The controls are read-only; do not add a write endpoint or an `onChange` handler.
- Only an active `package_type: "super_expert"` receives `harness_status`.
- Do not expose `agent.json`, paths, prompt files, Skill files, or runtime source.
- Missing or invalid explicit declarations project as `null`, never as an invented default.
- Ordinary Agent pages and ordinary sealed-agent packages do not show these controls.
- Preserve all unrelated dirty changes in both repositories.
- Do not commit unless the user explicitly requests it.

---

### Task 1: Add the read-only server projection

**Files:**
- Modify: `src/qwenpaw/config/config.py`
- Modify: `src/qwenpaw/app/routers/sealed_agents.py`
- Test: `tests/unit/app/test_sealed_agent_admin.py`

**Interfaces:**
- Consumes: active `SealedAgentRecord`, `runtime_workspace_root(...)`, and the active runtime workspace `agent.json`.
- Produces: `harness_status: {skill_reader_enabled: bool | None, agent_loop_enabled: bool | None} | None` in `_operational_dto`.

- [ ] **Step 1: Write failing configuration and projection tests**

Add tests that validate `OrchestrationConfig(agent_loop_enabled=True)` and create a temporary active super-expert runtime workspace with explicit true/false values. Assert `_operational_dto` projects the exact booleans, missing declarations project `None`, and an ordinary sealed package omits `harness_status`.

- [ ] **Step 2: Run the focused server tests and verify RED**

Run:

```bash
'.venv/bin/python' -m pytest \
  tests/unit/app/test_sealed_agent_admin.py \
  tests/unit/app/runner/test_workspace_orchestration.py -q
```

Expected: failures because `agent_loop_enabled` and `harness_status` do not exist.

- [ ] **Step 3: Add the nullable Agent Loop declaration**

Add this field to `OrchestrationConfig` without changing `_agent_execute_mode`:

```python
agent_loop_enabled: bool | None = Field(
    default=None,
    description="Whether this super expert declares full Agent Loop support",
)
```

- [ ] **Step 4: Implement narrow active-config projection**

Add a private helper in `sealed_agents.py` that:

1. returns `None` unless the active release is a super expert;
2. reads only `runtime_workspaces/<agent>/<release>/agent/agent.json`;
3. validates the document with `AgentProfileConfig`;
4. reads the explicit raw JSON paths for `read_agent_skill.enabled` and `orchestration.agent_loop_enabled`;
5. converts only JSON booleans and returns `None` per missing value;
6. catches file, JSON, and validation errors without exposing paths.

Add the result to `_operational_dto` only when the helper returns a status object.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

### Task 2: Render disabled switches in DClaw Console

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/api/modules/sealedAgents.ts`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/Settings/SealedAgents/index.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/Settings/SealedAgents/index.module.less`
- Test: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/Settings/SealedAgents/SealedAgents.test.tsx`

**Interfaces:**
- Consumes: nullable `SealedAgentOperational.harness_status` from Task 1.
- Produces: a read-only “Harness 能力” panel with two disabled Ant Design `Switch` controls.

- [ ] **Step 1: Write a failing UI test**

Return an agent fixture with both harness booleans, expand its row, and assert both named switches are visible, checked according to their values, and disabled. Add a missing-value assertion for the “未声明” label.

- [ ] **Step 2: Run the focused UI test and verify RED**

Run:

```bash
pnpm --dir console test:run \
  src/pages/Settings/SealedAgents/SealedAgents.test.tsx
```

Expected: failure because Harness controls are absent.

- [ ] **Step 3: Add the API type and read-only component**

Add:

```ts
harness_status?: {
  skill_reader_enabled: boolean | null;
  agent_loop_enabled: boolean | null;
};
```

Import `Switch`, render both values through a small local status row, omit the panel when `harness_status` is absent, and do not add an `onChange` handler.

- [ ] **Step 4: Add responsive panel styles**

Place the panel below the existing profile/banner row, span the full expanded width, and collapse the two status rows to one column on narrow screens.

- [ ] **Step 5: Run focused UI tests and verify GREEN**

Run the Step 2 command. Expected: all page tests pass.

### Task 3: Declare the two LuYu values in a new signed release

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/agent.json`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/VERSION.json`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/manifest.template.json`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/README.md`
- Test: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/tests/test_package_structure.py`

**Interfaces:**
- Consumes: `OrchestrationConfig.agent_loop_enabled` from Task 1.
- Produces: LuYu release `1.0.5` declaring both `read_agent_skill.enabled=true` and `orchestration.agent_loop_enabled=true`.

- [ ] **Step 1: Write the failing package assertion**

Assert `agent.json["orchestration"]["agent_loop_enabled"] is True` and all version-bearing files equal `1.0.5`.

- [ ] **Step 2: Run LuYu tests and verify RED**

Run:

```bash
'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' \
  -m pytest tests -q
```

Expected: failure because the declaration is absent and the version is `1.0.4`.

- [ ] **Step 3: Add the declaration and bump the package version**

Set `orchestration.agent_loop_enabled` to true, update version files to `1.0.5`, and retain the existing `runtime.py` request and Skill Reader configuration.

- [ ] **Step 4: Validate and build the signed ZIP**

Run the workspace validator, all LuYu tests, and `scripts/build_release.py` with the existing external local signing key. Verify the generated ZIP contains no tests, caches, outputs, or private key material and verify its SHA-256 sidecar.

### Task 4: Regression, deployment, and live verification

**Files:**
- Generated client build: `/Users/moxi/Desktop/codex space/dclaw-client/console/dist/**`
- Served client assets: `src/qwenpaw/console/**`
- Runtime deployment: current local `dclaw` container

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: the current local DClaw UI and active LuYu release showing the two real read-only states.

- [ ] **Step 1: Run server and client regression suites**

Run the focused server tests, full server pytest suite, Console page/API tests, TypeScript check, lint, and production build. Treat failures in unrelated dirty files as evidence to diagnose, not permission to overwrite those files.

- [ ] **Step 2: Synchronize exact reviewed files**

Copy the reviewed server modules into the running container, copy the production Console build into `src/qwenpaw/console` and the container serving directory, then restart only the `dclaw` service. Do not rebuild the dirty server image.

- [ ] **Step 3: Install and activate LuYu 1.0.5**

Upload through the existing sealed-release API, accept the full signed capability grant, activate the release, and verify runtime validation is valid.

- [ ] **Step 4: Verify the live API and UI**

Confirm `GET /api/admin/sealed-agents` reports both LuYu booleans as true, the browser page renders two checked disabled switches, ordinary Agents have no controls, and the container remains healthy.

- [ ] **Step 5: Record evidence**

Append exact test counts, release identity, digest, live DTO, and UI verification to the LuYu evaluation report without including prompts, Skill content, keys, or customer data.
