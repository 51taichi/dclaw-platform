# Sealed Agent Capability-Parity Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic, single-entrypoint sealed runtime that preserves trusted package execution and existing DClaw model/tool capabilities without changing non-sealed Agent behavior.

**Architecture:** A sealed package declaring `sealed_entrypoint/1` runs its own controller inside an isolated process with read-only release files and a persistent per-session directory. The process requests the existing DClaw AgentScope model/tool loop through a bounded `agent.execute` host RPC and returns exactly one final reply plus optional diagnostics; DClaw never names or sequences Agent-specific stages.

**Tech Stack:** Python 3.10, FastAPI, Pydantic, asyncio subprocesses, bubblewrap, AgentScope, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-sealed-agent-capability-parity-runtime-design.md`

## Global Constraints

- Only sealed-Agent infrastructure and its tests may change; non-sealed Agent execution behavior must remain unchanged.
- Sealing must not remove any trusted package capability; any confirmed capability loss blocks activation.
- DClaw must not contain Agent-specific stages, Skill names, state names, or debug field names.
- Model-visible tools must not expose sealed release files or arbitrary release-directory shell access.
- A sealed invocation must publish exactly one final customer-visible reply.
- Existing `standard/1` and `sealed_harness/1` releases remain compatible.
- New packages opt in only through Manifest `adapter="sealed_entrypoint"` and `contract_version="1"`.
- Failures are fail-closed and never fall back to the standard model path.

---

### Task 1: Define the generic entrypoint protocol and package declaration

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/entrypoint_protocol.py`
- Modify: `src/qwenpaw/app/sealed_agents/adapters.py`
- Modify: `src/qwenpaw/app/sealed_agents/service.py`
- Test: `tests/unit/app/sealed_agents/test_entrypoint_protocol.py`
- Test: `tests/unit/app/sealed_agents/test_adapters.py`
- Test: `tests/unit/app/sealed_agents/test_service.py`

**Interfaces:**
- Produces `RuntimeInvoke`, `HostCall`, `HostResult`, `RuntimeFinal`, `RuntimeReady`, and `EntrypointProtocolError` Pydantic models.
- Registers adapter key `("sealed_entrypoint", "1")` without changing existing adapter keys.
- Makes release validation select the protocol appropriate to the pinned adapter.

- [ ] **Step 1: Write failing protocol-model tests**

Add literal contract tests that accept a valid `runtime.invoke`, reject unknown fields, reject mismatched protocol versions, require a non-empty final reply, and reject unsupported capabilities.

```python
def test_runtime_final_requires_one_non_empty_reply():
    with pytest.raises(ValidationError):
        RuntimeFinal(
            type="runtime.final",
            protocol_version="1",
            invocation_id="inv-1",
            message_id="final-1",
            reply="",
            artifacts=[],
            diagnostics=None,
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/app/sealed_agents/test_entrypoint_protocol.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_service.py`

Expected: collection or assertion failure because the generic models and adapter do not exist.

- [ ] **Step 3: Implement strict protocol models and register the adapter key**

Use `ConfigDict(extra="forbid", frozen=True)`, literal message types, a one-megabyte encoded-message limit, depth limit 32, and capability literal `agent.execute`. Keep `standard/1` and `sealed_harness/1` registrations unchanged.

- [ ] **Step 4: Make service validation dispatch by adapter type**

Keep `standard/1` validation unchanged, keep `sealed_harness/1` on its existing handshake, and route `sealed_entrypoint/1` to the generic entrypoint handshake introduced in Task 2.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/entrypoint_protocol.py src/qwenpaw/app/sealed_agents/adapters.py src/qwenpaw/app/sealed_agents/service.py tests/unit/app/sealed_agents/test_entrypoint_protocol.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_service.py
git commit -m "feat: define generic sealed entrypoint protocol"
```

### Task 2: Run a package entrypoint with persistent session storage and bounded host RPC

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/entrypoint_worker.py`
- Modify: `src/qwenpaw/app/sealed_agents/entrypoint_protocol.py`
- Create: `tests/fixtures/sealed_entrypoint/agent/runtime.py`
- Test: `tests/unit/app/sealed_agents/test_entrypoint_protocol.py`

**Interfaces:**
- Produces `SealedEntrypointProcess(pinned, session_root, ...)`.
- Produces `await process.handshake()` and `await process.invoke(payload, host_handler)`.
- `host_handler(capability: str, arguments: dict[str, Any]) -> Awaitable[dict[str, Any]]` is the only route from a sealed package to DClaw services.

- [ ] **Step 1: Write failing process tests**

Add real subprocess tests proving that the fixture can read a release resource, increment a counter in the supplied session directory across two process invocations, request `agent.execute`, return exactly one final object, and fail on a second final object or unknown capability.

```python
@pytest.mark.asyncio
async def test_entrypoint_persists_same_session_and_calls_host(tmp_path):
    first = await invoke_fixture(tmp_path, session_name="session-a")
    second = await invoke_fixture(tmp_path, session_name="session-a")
    isolated = await invoke_fixture(tmp_path, session_name="session-b")
    assert first.reply == "host reply / turn 1"
    assert second.reply == "host reply / turn 2"
    assert isolated.reply == "host reply / turn 1"
```

- [ ] **Step 2: Run the process tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/app/sealed_agents/test_entrypoint_protocol.py`

Expected: failure because the worker and process driver do not exist.

- [ ] **Step 3: Implement the isolated worker**

Load `create_runtime()` from the signed entrypoint. Support only `runtime.handshake` and `runtime.invoke`. Provide a worker-side `host.call()` object that writes a bounded `host.call`, blocks for the matching `host.result`, and never exposes environment secrets or host filesystem paths.

- [ ] **Step 4: Implement the host-side process driver**

Use bubblewrap with `/release` read-only, the supplied `/session` read-write, `/tmp` temporary, network unshared, bounded stderr, process-group termination, per-call timeout, total timeout, maximum 64 host calls, message-size limit, depth limit, and invocation/call ID matching.

- [ ] **Step 5: Run the process tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/entrypoint_worker.py src/qwenpaw/app/sealed_agents/entrypoint_protocol.py tests/fixtures/sealed_entrypoint/agent/runtime.py tests/unit/app/sealed_agents/test_entrypoint_protocol.py
git commit -m "feat: execute sealed package entrypoints with host rpc"
```

### Task 3: Add the generic adapter with one final reply and generic diagnostics

**Files:**
- Modify: `src/qwenpaw/app/sealed_agents/adapters.py`
- Modify: `src/qwenpaw/app/sealed_agents/request_context.py`
- Test: `tests/unit/app/sealed_agents/test_adapters.py`
- Test: `tests/unit/app/sealed_agents/test_request_context.py`

**Interfaces:**
- Produces `SealedEntrypointAdapterV1` with key `("sealed_entrypoint", "1")`.
- Extends `SealedAdapterRequest` with trusted `session_root: Path` and `diagnostics_authorized: bool` fields rather than Agent-specific debug flags.
- Converts `agent.execute` host calls into the existing `model_executor(messages, controlled_context)` function.

- [ ] **Step 1: Write failing adapter tests**

Add tests proving that one host call receives the complete model/tool message result, only one final `Msg` is yielded, diagnostics are attached only when trusted authorization is true, package metadata cannot grant authorization, malformed final responses fail closed, and an exception never invokes standard fallback.

```python
assert len(result) == 1
assert result[0][0].get_text_content() == "final reply"
assert result[0][1] is True
assert result[0][0].metadata["sealed_runtime_diagnostics"]["agent"] == {"stage": "S1"}
```

- [ ] **Step 2: Run the adapter tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_request_context.py`

Expected: failure because the new adapter and request fields do not exist.

- [ ] **Step 3: Implement the adapter and generic diagnostics envelope**

Build `runtime.invoke` from trusted release/session identity plus untrusted metadata. Allow only `agent.execute`; collect the existing model/tool loop into structured messages; accept one `runtime.final`; return one assistant `Msg`. When authorized, attach `{runtime: {release_id, version, content_digest, adapter, contract_version}, agent: <package diagnostics>}` under `sealed_runtime_diagnostics`.

- [ ] **Step 4: Remove DClaw's Agent-specific debug interpretation**

In the legacy adapter, stop checking `luyu_debug`. If the legacy package emits `debug`, attach it only when the trusted generic diagnostics authorization is true. Preserve the legacy stage sequence solely for already-installed `sealed_harness/1` releases.

- [ ] **Step 5: Run the adapter tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/adapters.py src/qwenpaw/app/sealed_agents/request_context.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_request_context.py
git commit -m "feat: add capability-equivalent sealed entrypoint adapter"
```

### Task 4: Wire only opted-in sealed releases into Runner

**Files:**
- Modify: `src/qwenpaw/app/runner/runner.py`
- Modify: `src/qwenpaw/app/sealed_agents/runtime.py`
- Test: `tests/unit/app/sealed_agents/test_runtime.py`
- Create: `tests/unit/app/runner/test_sealed_entrypoint_isolation.py`

**Interfaces:**
- Uses `create_runtime_context()` to derive persistent `/sealed_sessions/<agent>/<session>` storage.
- Selects the generic adapter only for a pinned sealed release declaring `sealed_entrypoint/1`.
- Keeps non-sealed and legacy sealed standard execution on their existing branches.

- [ ] **Step 1: Write failing isolation tests**

Add a Runner-level test with an adapter resolver that raises if touched, then execute a non-sealed request and assert the existing model result succeeds. Add sealed tests proving the same session root is reused, different sessions differ, active-release changes do not alter an already pinned invocation, and entrypoint failure never calls the standard executor.

- [ ] **Step 2: Run the isolation tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/app/runner/test_sealed_entrypoint_isolation.py tests/unit/app/sealed_agents/test_runtime.py`

Expected: failure because Runner cannot execute `sealed_entrypoint/1` and does not pass persistent storage.

- [ ] **Step 3: Implement sealed-only Runner selection**

Build the persistent session root only after `sealed_runtime` and a pinned opt-in release are confirmed. Pass generic trusted identity and normalized caller metadata through `SealedAdapterRequest`. Resolve and call the registered adapter for `sealed_harness/1` or `sealed_entrypoint/1`; retain the existing standard executor for non-sealed and `standard/1` paths.

- [ ] **Step 4: Ensure output policy runs once on the single final reply**

Sanitize only the adapter's final `Msg`. Do not yield model drafts or host-call messages. Preserve existing non-sealed streaming behavior.

- [ ] **Step 5: Run the isolation tests and existing Runner tests**

Run: `.venv/bin/pytest -q tests/unit/app/runner tests/unit/app/sealed_agents/test_runtime.py tests/integration/test_console_billing_flow.py`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/runner/runner.py src/qwenpaw/app/sealed_agents/runtime.py tests/unit/app/sealed_agents/test_runtime.py tests/unit/app/runner/test_sealed_entrypoint_isolation.py
git commit -m "feat: isolate sealed entrypoint execution in runner"
```

### Task 5: Authorize and return diagnostics without exposing them to customers

**Files:**
- Modify: `src/qwenpaw/app/open_api/models.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Test: `tests/unit/app/sealed_agents/test_open_api_sealed.py`
- Test: `tests/unit/app/test_open_api_router.py`
- Test: `tests/unit/app/test_open_api_admin.py`

**Interfaces:**
- Adds generic OpenAPI scope `diagnostics:read`.
- Treats diagnostics as authorized only when the request asks for `metadata.diagnostics_requested is true` and both the current API key and publication include `diagnostics:read`.
- Emits a separate `response.diagnostics` SSE event only when the final sealed message already contains trusted diagnostics metadata.

- [ ] **Step 1: Write failing authorization and serialization tests**

Cover four literal cases: ordinary key plus request flag returns only text; diagnostics-scoped key without request flag returns only text; both scopes plus request flag returns text and one diagnostics event; non-sealed target never receives `_server_debug_endpoint_authorized` even when scopes and metadata are present.

- [ ] **Step 2: Run the OpenAPI tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/app/sealed_agents/test_open_api_sealed.py tests/unit/app/test_open_api_router.py tests/unit/app/test_open_api_admin.py`

Expected: failure because the scope and diagnostics event do not exist.

- [ ] **Step 3: Implement scope-based trusted authorization**

Read key/publication scopes from `request.state.open_auth_context`. Set the private server flag only for sealed targets when both scope sets contain `diagnostics:read` and the exact JSON boolean request flag is true. Do not treat user text, strings, numbers, or unscoped metadata as authorization.

- [ ] **Step 4: Emit diagnostics separately from reply**

For completed sealed assistant messages, emit `response.output_text.delta` for customer text and, when present, `response.diagnostics` for the trusted metadata envelope. Never concatenate diagnostics into reply text. Keep the public event allowlist closed.

- [ ] **Step 5: Run the OpenAPI tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/open_api/models.py src/qwenpaw/app/open_api/runtime.py src/qwenpaw/app/routers/open_api.py tests/unit/app/sealed_agents/test_open_api_sealed.py tests/unit/app/test_open_api_router.py tests/unit/app/test_open_api_admin.py
git commit -m "feat: add scoped sealed runtime diagnostics"
```

### Task 6: Full sealed and ordinary-Agent regression verification

**Files:**
- Test only: existing DClaw suites

**Interfaces:**
- Produces fresh evidence that sealed functionality works and ordinary Agent paths remain unchanged.

- [ ] **Step 1: Run formatting and static checks on changed Python files**

Run: `.venv/bin/ruff check src/qwenpaw/app/sealed_agents src/qwenpaw/app/runner/runner.py src/qwenpaw/app/open_api src/qwenpaw/app/routers/open_api.py tests/unit/app/sealed_agents tests/unit/app/runner/test_sealed_entrypoint_isolation.py`

Expected: zero errors.

- [ ] **Step 2: Run the full sealed/OpenAPI/Runner regression suite**

Run: `.venv/bin/pytest -q tests/unit/app/sealed_agents tests/unit/app/runner tests/unit/app/test_open_api_router.py tests/unit/app/test_open_api_admin.py tests/unit/app/billing/test_open_api_billing.py tests/integration/test_console_billing_flow.py tests/integration/test_open_api_billing_flow.py`

Expected: zero failures.

- [ ] **Step 3: Run ordinary Agent tool and workspace regressions**

Run: `.venv/bin/pytest -q tests/unit/agents tests/unit/workspace tests/unit/routers/test_agents.py tests/unit/routers/test_providers.py`

Expected: zero failures. Any failure in an untouched dirty-main file must be reproduced against the isolated branch baseline before attribution.

- [ ] **Step 4: Verify the change boundary**

Run: `git diff --name-only 995dbf7...HEAD`

Expected: only sealed runtime files, the minimum guarded Runner/OpenAPI integration files, sealed/Runner/OpenAPI tests, and this plan/spec are listed. No Agent workspace or unrelated DClaw feature file may appear.

- [ ] **Step 5: Run diff hygiene checks**

Run: `git diff --check 995dbf7...HEAD && git status --short`

Expected: no whitespace errors and no untracked implementation artifacts.
