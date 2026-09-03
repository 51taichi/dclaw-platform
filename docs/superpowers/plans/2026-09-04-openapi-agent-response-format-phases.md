# OpenAPI Agent Response-Format Phases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent `response_format=json_object` from entering OpenAPI Agent planning/tool/internal calls, apply it only to the validated final customer reply, and return durable explicit OpenAPI failures instead of successful empty output.

**Architecture:** Add a request-scoped model adapter around the fully wrapped Agent model. The adapter buffers planning responses, forwards tool calls unchanged, and performs a tool-free finalization call when planning produces a candidate answer. It is installed only after Runner derives a trusted direct-Agent OpenAPI marker from server-owned channel metadata. Stable typed failures flow through the existing SSE/billing finalizer, which seals the same failure in the invocation record and terminal event.

**Tech Stack:** Python 3.10, AgentScope `ChatModelBase`/`ChatResponse`, FastAPI SSE, pytest/pytest-asyncio, existing OpenAPI billing execution fence.

**Spec:** `docs/superpowers/specs/2026-09-04-openapi-agent-response-format-phases-design.md`

## Global Constraints

- Do not mutate Provider configuration or reuse phase state across requests.
- Keep every supplier call inside the existing Retry and BillingModelMeter wrappers.
- Do not enable the adapter for console, normal tasks, scheduled tasks, external channels, OpenAPI expert teams, AIGC, or models without `json_object` configuration.
- Planning text is private and must not be emitted or persisted as the final assistant answer.
- Final customer output must be a non-empty JSON object when `json_object` is configured.
- Use stable safe public errors; never expose provider bodies, credentials, stack traces, or local paths.

---

## Task 1: Establish the trusted activation boundary

**Files:**

- Modify: `src/qwenpaw/app/runner/runner.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Create: `src/qwenpaw/app/open_api/agent_response_format.py`
- Test: `tests/unit/app/runner/test_open_api_response_format_activation.py`
- Test: `tests/unit/app/test_open_api_router.py`

- [ ] Write tests proving that only server-owned metadata with `channel=open:*`, `target_type=agent`, `publication_id`, and `open_invocation_id` activates the policy after caller context merging.
- [ ] Write a request-preparation test proving ordinary and isolated direct-Agent OpenAPI requests both receive the server-created invocation ID, while the request body cannot replace it.
- [ ] Add negative tests for console, ordinary channels, forged payload context, missing invocation/publication identity, and `target_type=expert_team`.
- [ ] Run the new test file and confirm the tests fail because no trusted marker/installer exists.
- [ ] Add a small pure helper that derives `_open_api_direct_agent_execution` from channel metadata and overwrites any caller-provided value.
- [ ] Attach `open_invocation_id` to native metadata whenever the router has created an invocation, not only for `isolated_attempt`.
- [ ] Install the request-scoped adapter on the newly constructed `QwenPawAgent` only when the trusted marker is true.
- [ ] Run the new activation tests and existing isolated OpenAPI runner tests.
- [ ] Commit the activation boundary and tests.

## Task 2: Implement planning, internal, and finalizing model phases

**Files:**

- Modify: `src/qwenpaw/app/open_api/agent_response_format.py`
- Modify: `src/qwenpaw/providers/openai_chat_model_compat.py`
- Test: `tests/unit/app/open_api/test_agent_response_format.py`
- Test: `tests/unit/providers/test_openai_stream_toolcall_compat.py`

- [ ] Build a fake streaming chat model and write failing tests for a no-tool JSON reply: planning omits configured `response_format`, finalization has it, tools are absent in finalization, and only the validated final response is returned.
- [ ] Add failing state-machine tests for native tool calls and tag-parsed tool calls, proving every planning turn omits `response_format` and the final turn restores it.
- [ ] Add failing internal-call tests proving `structured_model` operations use tool-call structured output without the configured JSON response format.
- [ ] Add named-tool fixtures representing knowledge-base search, MCP, and Excel skill tools and assert their selection/execution planning calls never contain `response_format`.
- [ ] Implement wrapper discovery that activates only for `OpenAIChatModelCompat` with exact `{"type": "json_object"}` effective configuration.
- [ ] Implement buffering/replay utilities that preserve response IDs, content blocks, usage, supplier references, and the existing Retry/BillingModelMeter call boundary.
- [ ] Implement Planning behavior: override the configured format with the OpenAI SDK omission sentinel, preserve tools/tool choice, return tool calls unchanged, and suppress candidate planning text.
- [ ] Implement Finalizing behavior: append a non-persisted finalization instruction and planning draft to a copied prompt, omit tools/tool choice, restore the snapshotted format, buffer and validate before replay.
- [ ] Force internal `structured_model` calls through AgentScope's tool-call fallback on this request-owned OpenAI model instance so no `response_format` is sent.
- [ ] Run the focused adapter/provider tests and confirm all phase assertions pass.
- [ ] Commit the phase adapter and tests.

## Task 3: Define typed safe execution failures

**Files:**

- Modify: `src/qwenpaw/app/open_api/agent_response_format.py`
- Test: `tests/unit/app/open_api/test_agent_response_format.py`

- [ ] Write failing tests for empty final text, whitespace, invalid JSON, JSON array, JSON scalar, and valid empty object `{}`.
- [ ] Write failing tests for supplier exceptions before the first chunk and after a partial chunk; assert no partial model answer is replayed as success.
- [ ] Write failing tests for an unrecoverable tool failure/no valid final response and a recoverable tool error followed by a valid final response.
- [ ] Add `OpenApiAgentExecutionError` carrying stable `code`, safe `message`, `http_status`, and private `error_summary`; define `model_execution_failed`, `tool_execution_failed`, `empty_final_response`, and `invalid_final_response` constructors/mapping.
- [ ] Validate final content as a JSON object before exposing it and map model/tool failures without leaking supplier details.
- [ ] Run the focused adapter tests.
- [ ] Commit typed failure behavior and tests.

## Task 4: Seal failures consistently in SSE and invocation records

**Files:**

- Modify: `src/qwenpaw/app/routers/open_api.py`
- Test: `tests/unit/app/test_open_api_router.py`
- Test: `tests/integration/test_open_api_billing_flow.py`

- [ ] Write failing router tests for stable failed terminal events from model, tool, empty-final, and invalid-final errors, including `status=failed`, `code`, safe `message`, and `http_status`.
- [ ] Assert the invocation row's status, status code, error summary, and `terminal_event_json` match the final SSE terminal event.
- [ ] Add a test that a supplier error occurring after partial upstream output cannot produce a successful terminal event.
- [ ] Add an idempotent replay test proving a sealed failure is replayed without calling the producer/model again.
- [ ] Replace tuple-only stream failure handling with a small structured failure value understood by `_extract_stream_failure` and `_shielded_finalize`.
- [ ] Map typed OpenAPI execution exceptions to their stable terminal payload; keep unrelated exceptions as generic safe `request_failed`.
- [ ] Run focused router and billing-flow tests.
- [ ] Commit SSE and durable failure sealing.

## Task 5: Prove scope isolation and full regression safety

**Files:**

- Test: `tests/unit/app/runner/test_open_api_response_format_activation.py`
- Test: `tests/unit/app/open_api/test_agent_response_format.py`
- Test: `tests/unit/agents/test_react_agent_prompt_workspace.py`
- Test: `tests/integration/test_open_api_billing_flow.py`

- [ ] Add/finish negative tests proving the exact same configured model remains unchanged for console, normal task, scheduled/automation, non-OpenAPI knowledge/skill/MCP, expert-team OpenAPI, and AIGC paths.
- [ ] Add a compatibility test proving OpenAPI Agent models without exact `json_object` configuration retain the original one-call streaming behavior.
- [ ] Run formatting/lint checks on every changed Python file.
- [ ] Run all focused tests from Tasks 1-4.
- [ ] Run the broader OpenAPI, Agent, provider, console, task, and AIGC regression suites selected by changed-code impact.
- [ ] Inspect `git diff --check`, `git status`, and the final diff for scope leaks, debug artifacts, secrets, or unrelated changes.
- [ ] Commit final non-regression coverage/documentation adjustments.

## Completion Criteria

- DeepSeek never receives configured `response_format=json_object` together with Agent tools in a direct OpenAPI Agent invocation.
- Knowledge-base rewrite, MCP, skills, Excel, and every other internal/planning call omit that configured response format.
- The sole customer answer comes from a tool-free JSON finalization call and is validated before exposure.
- Supplier failures, unrecoverable tool failures, empty final output, and invalid final JSON produce explicit sealed OpenAPI failures.
- All supplier calls remain metered and all non-target entry points retain their previous behavior.
