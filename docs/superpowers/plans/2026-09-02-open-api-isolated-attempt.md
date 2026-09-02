# OpenAPI Isolated Attempt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add request-local session-state and long-term-memory isolation exclusively for Agent-target OpenAPI calls that explicitly request `execution_mode: "isolated_attempt"`.

**Architecture:** The OpenAPI router validates target eligibility and supplies the billing invocation ID to preparation. Preparation derives a unique execution session ID and trusted internal policy only for isolated Agent calls, avoids durable chat creation, and retains the normal Agent workspace object and ConsoleChannel. AgentRunner recognizes only that narrowly validated trusted policy, omits session persistence and the shared MemoryManager, but preserves configuration, context manager, skills, knowledge, MCP clients, tools, streaming, and artifacts.

**Tech Stack:** Python 3.10, FastAPI/Pydantic, AgentScope runtime, pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-02-open-api-isolated-attempt-design.md`

## Global Constraints

- Only Agent-target `POST /api/open/v1/targets/{public_id}/messages` with explicit `execution_mode: "isolated_attempt"` enters the new branch.
- Omitted mode and explicit `persistent` retain current behavior and payload shape.
- Expert teams and every non-OpenAPI entry point remain outside the isolation branch.
- Preserve Agent configuration, prompt identity, skills, knowledge base, configured tools, MCP clients, and artifact delivery.
- Do not delete successful artifacts or introduce general tool filtering.
- Do not commit until the user reviews the final impact and test matrix.

---

### Task 1: Protocol and Agent-only routing boundary

**Files:**
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Test: `tests/unit/app/test_open_api_router.py`

**Interfaces:**
- Produces: `OpenMessageRequest.execution_mode: Literal["persistent", "isolated_attempt"] = "persistent"`.
- Produces: isolated preparation parameters carrying the server billing invocation ID.
- Preserves: persistent `build_open_session_id` output and native payload.

- [ ] Add schema tests for omitted, persistent, isolated, and invalid values.
- [ ] Run those tests and verify they fail because the field/validation is absent.
- [ ] Add route tests proving expert-team isolated requests return 400 before preparation while persistent teams remain unchanged.
- [ ] Run those tests and verify the missing boundary causes the expected failures.
- [ ] Implement the typed field and Agent-only route guard with no persistent-path metadata changes.
- [ ] Run the focused schema/router tests to green.

### Task 2: Unique isolated execution identity without durable chat records

**Files:**
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Test: `tests/unit/app/test_open_api_router.py`

**Interfaces:**
- Produces: unique internal `session_id` derived from the stable OpenAPI namespace plus server invocation identity.
- Produces: trusted top-level native metadata identifying Agent OpenAPI isolated execution.
- Preserves: caller `external_session_id` and frozen business payload.

- [ ] Add tests proving three equal isolated inputs retain identical business/external fields but receive distinct internal session IDs.
- [ ] Add tests proving nested caller metadata cannot forge the trusted policy or execution ID.
- [ ] Add tests proving isolated preparation skips `get_or_create_chat`, uses an ephemeral tracker ID, and persistent preparation still creates the current chat.
- [ ] Run the tests and verify failures occur on current stable-session/chat behavior.
- [ ] Implement isolated identity/policy preparation and ephemeral tracker identity; leave persistent preparation unchanged.
- [ ] Run focused preparation and router tests to green.

### Task 3: Runner session-state and long-term-memory isolation

**Files:**
- Modify: `src/qwenpaw/app/runner/runner.py`
- Test: `tests/unit/app/runner/test_open_api_isolated_attempt.py`

**Interfaces:**
- Consumes: trusted native metadata from Task 2.
- Produces: a request-local isolation decision that cannot be activated by console, ordinary Agent, team, scheduled, background, mission/orchestration, or inter-Agent metadata.

- [ ] Build a focused runner harness around a real `AgentRunner.query_handler` with fake storage/model boundaries and write a persistent characterization test for session preflight/load/save, chat create/touch, and shared MemoryManager injection.
- [ ] Run the characterization test and verify it passes before production changes.
- [ ] Write isolated tests proving zero session get/update/load/save, zero chat create/touch, and `memory_manager=None` at Agent construction.
- [ ] Run them and verify they fail against current unconditional behavior.
- [ ] Write negative-entry tests proving similarly named metadata on non-OpenAPI channels and non-Agent target metadata cannot activate isolation.
- [ ] Run them and verify the overly broad implementation is not introduced.
- [ ] Implement one narrow predicate and branch the existing runner lifecycle around session/chat persistence and MemoryManager injection.
- [ ] Run persistent, isolated, and negative-entry runner tests to green.

### Task 4: Capability and workspace equivalence

**Files:**
- Modify only if required: `src/qwenpaw/agents/react_agent.py`
- Test: `tests/unit/agents/test_open_api_isolated_attempt.py`
- Test: `tests/unit/agents/test_react_agent_prompt_workspace.py`
- Test: `tests/unit/agents/test_react_agent_skill_registration.py`

**Interfaces:**
- Consumes: unique isolated root session ID and `memory_manager=None`.
- Preserves: prompt/skills roots, Agent config, knowledge ID, builtin/plugin/MCP registrations, and writable per-session boundary.

- [ ] Add tests comparing persistent and isolated Agent construction for identical prompt root, skills root, configuration, knowledge metadata, non-memory tools, and MCP client inputs.
- [ ] Add tests proving the isolated workspace root is unique while prompt and skills roots remain the configured Agent root.
- [ ] Add tests proving memory tools/hooks disappear only when the MemoryManager is absent.
- [ ] Run tests; if existing `QwenPawAgent` behavior already satisfies them, make no production change in this file.
- [ ] If a gap exists, implement only the minimal request-local boundary needed and rerun to green.

### Task 5: Three-attempt, concurrency, history, and artifact acceptance

**Files:**
- Test: `tests/integration/test_open_api_isolated_attempt.py`
- Modify only if a proven gap exists: files from Tasks 1–4.

**Interfaces:**
- Exercises the public request model through preparation, ConsoleChannel/runner boundaries, session storage, chat storage, and artifact delivery.

- [ ] Write an integration test issuing three isolated attempts with frozen input and correlation fields; assert unique execution roots and no cross-attempt model output, state, memory, or file visibility.
- [ ] Write an integration test proving no isolated chat/message/session rows are created and invocation audit retains the external session correlation.
- [ ] Write an artifact test proving `send_file_to_user`/artifact-card output remains consumable and successful files remain after stream completion.
- [ ] Write a concurrency test running isolated and persistent requests together; assert the persistent session, chat/history, memory, and workspace behavior is unchanged.
- [ ] Run each test red, make only the minimal implementation corrections, then rerun green.

### Task 6: Documentation and verification checkpoint

**Files:**
- Modify: `docs/open-api-user-manual.zh.md`
- Modify: `docs/superpowers/specs/2026-09-02-open-api-isolated-attempt-design.md`
- Modify: `docs/superpowers/plans/2026-09-02-open-api-isolated-attempt.md`

**Interfaces:**
- Documents the caller contract, Agent-only restriction, live artifact lifecycle, and non-transactional tool boundary.

- [ ] Document omitted/persistent/isolated request examples and the requirement that every AIBot candidate, including the first, use isolated mode with frozen business input.
- [ ] Run focused OpenAPI, runner, Agent, chat-list, artifact, billing, and concurrency tests.
- [ ] Run formatter/linter only against task-modified Python files.
- [ ] Run `git diff --check`, inspect `git status --short`, and confirm no unrelated files are staged.
- [ ] Report final impact surface, exact test matrix/results, modified files, known baseline failure, and remaining risks; wait for user approval before staging or committing.
- [ ] After approval, verify repository root and both remote URLs, stage explicit task files only, commit, and push to `git@github.com:51taichi/dclaw-server.git`.
