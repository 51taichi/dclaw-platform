# DClaw Basic Interaction Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned DClaw interaction capability catalog with real single/multi-select cards, convert trusted submissions into ordinary user input, and migrate LuYu closed-choice prompts to use it.

**Architecture:** DClaw Server owns an immutable interaction catalog, strict domain models, a file-locked repository, authorized Agent tools, and REST submission. The submit route returns trusted `user_input` immediately and never invokes or waits for a model. DClaw Client restores and renders interaction cards above the composer, disables all message entry points for active `card_only` cards, and sends `user_input` through the existing ordinary chat submission path. LuYu declares the new capabilities and uses the live catalog for every closed-choice customer question while leaving open questions as normal text.

**Tech Stack:** Python 3.10+, Pydantic v2, FastAPI, pytest, React 18, TypeScript 5.8, Vitest, Testing Library, CSS Modules/Less, DClaw schema v3.

**Spec:** `docs/superpowers/specs/2026-09-17-basic-interaction-capabilities-design.md`

## Global Constraints

- Work only in local isolated worktrees; do not push, package, build an image, deploy, or update production.
- Preserve the existing AIGC contracts and do not reuse AIGC material/canvas identifiers for interaction cards.
- `card_only` is the default input policy and only takes effect after a real persisted card exists.
- Published v1 contracts are strict and additive; unknown fields are rejected.
- The platform never silently converts a failed card creation into a text A/B/C prompt.
- Existing uncommitted Client `VERSION` and Tauri changes remain untouched in the main checkout.
- Do not create intermediate Git commits; the user requested one consolidated commit per Git repository after local validation and explicit confirmation.

---

### Task 1: Define and validate the interaction catalog

**Files:**
- Create: `src/qwenpaw/app/super_experts/interaction_contract.py`
- Create: `tests/unit/app/super_experts/test_interaction_contract.py`
- Modify: `src/qwenpaw/app/super_experts/capabilities.py`
- Modify: `tests/unit/app/sealed_agents/test_super_expert_manifest.py`

**Interfaces:**
- Produces: `InteractionComponentType`, `InteractionInputPolicy`, `InteractionStatus`, `InteractionOption`, `SingleSelectCard`, `MultiSelectCard`, `InteractionCreateRequest`, `InteractionAnswer`, `build_interaction_catalog(component_types: list[str]) -> dict[str, Any]`, and `validate_card(component_type: str, card: dict[str, Any])`.
- Produces capabilities `interaction.capabilities.list/1`, `interaction.card.create/1`, and `interaction.card.cancel/1` in group `interaction` version `1`.

- [x] **Step 1: Write catalog tests that name the contract breaks**

```python
def test_catalog_index_is_small_and_points_to_two_distinct_components():
    catalog = build_interaction_catalog([])
    assert [item["component_type"] for item in catalog["components"]] == [
        "single_select", "multi_select",
    ]
    assert "schema" not in catalog["components"][0]


def test_single_select_rejects_two_defaults():
    with pytest.raises(InteractionValidationError) as error:
        validate_card("single_select", {
            "title": "选一个",
            "options": [
                {"text": "甲", "default_selected": True},
                {"text": "乙", "default_selected": True},
            ],
        })
    assert error.value.issues == [{"field": "card.options", "code": "TOO_MANY_DEFAULTS"}]


def test_multi_select_enforces_bounds_and_optional_supplement():
    card = validate_card("multi_select", {
        "title": "可多选",
        "options": [{"id": "a", "text": "甲"}, {"text": "乙"}],
        "min_selections": 1,
        "max_selections": 2,
        "supplement": {"enabled": True, "required": False},
    })
    assert card.supplement.required is False
```

- [x] **Step 2: Run the tests and verify they fail because the contract module and capabilities do not exist**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/super_experts/test_interaction_contract.py tests/unit/app/sealed_agents/test_super_expert_manifest.py -q`

Expected: collection/import or assertions fail specifically for missing interaction contract/capabilities.

- [x] **Step 3: Implement frozen Pydantic models and one authoritative catalog builder**

Implement literal limits from the spec, strict `extra="forbid"`, per-option ID/text uniqueness, default-selection constraints, multi-select bounds, supplement validation, concise index responses, and detailed filtered responses containing schemas plus concrete correct/error examples.

- [x] **Step 4: Add the three platform capabilities and dependency closure**

`interaction.card.create/1` depends on `interaction.capabilities.list/1`; `interaction.card.cancel/1` depends on `interaction.card.create/1`. Add group-version manifest coverage without changing existing AIGC definitions.

- [x] **Step 5: Run focused tests and `git diff --check`**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/super_experts/test_interaction_contract.py tests/unit/app/sealed_agents/test_super_expert_manifest.py -q`

Expected: all selected tests pass with no new warnings from project code.

### Task 2: Persist interaction cards and enforce state transitions

**Files:**
- Create: `src/qwenpaw/app/super_experts/interaction_cards.py`
- Create: `tests/unit/app/super_experts/test_interaction_cards.py`
- Modify: `src/qwenpaw/app/super_experts/composition.py`

**Interfaces:**
- Consumes: strict requests and answers from `interaction_contract.py`.
- Produces: `InteractionBinding`, `InteractionCardRecord`, `InteractionCardRepository`, and `InteractionService.create/cancel/submit/get/list_for_conversation`.

- [x] **Step 1: Write repository and service tests first**

Cover deterministic IDs, identical replay, divergent replay conflict, one active blocking card, explicit atomic replacement, cancellation, expiry projection, cross-installation/session rejection, valid single/multi answers, required supplement, stale version, and concurrent double submit.

```python
def test_second_blocking_card_requires_explicit_replacement(service):
    first = service.create(request("first"))
    with pytest.raises(InteractionError) as error:
        service.create(request("second"))
    assert error.value.code == "ACTIVE_BLOCKING_INTERACTION_EXISTS"
    second = service.create(request("second", replaces=first.interaction_id))
    assert service.get(first.interaction_id).status == "REPLACED"
    assert second.status == "PENDING"
```

- [x] **Step 2: Run and verify RED**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/super_experts/test_interaction_cards.py -q`

Expected: fail because repository/service are missing.

- [x] **Step 3: Implement file-locked persistence and immutable transitions**

Use the existing `JsonFileLock` pattern, atomic temporary-file replacement, a per-process lock, an append-only transition tuple, and persisted idempotency records. Do not add test-only reset methods to production classes.

- [x] **Step 4: Implement validation at transition time**

Resolve selected options from the persisted card, never from client-provided labels. Return both stored ID when present and full text. Only transition `PENDING`; require matching version and enforce supplement/selection bounds inside the same lock.

- [x] **Step 5: Run focused tests and mutation-check the branches**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/super_experts/test_interaction_cards.py -q`

Expected: pass; mentally changing the blocking-card check, version check, or first-writer rule would fail at least one test.

### Task 3: Expose authorized Agent tools

**Files:**
- Create: `src/qwenpaw/app/workspace/interaction_tools.py`
- Create: `tests/unit/app/runner/test_interaction_tools.py`
- Modify: `src/qwenpaw/app/workspace/orchestration.py`
- Modify: `src/qwenpaw/app/runner/runner.py`

**Interfaces:**
- Consumes: the interaction capabilities through the existing `business_call` host boundary.
- Produces: `build_interaction_tools(...)` and `bind_interaction_tools(...)` with model tool names from the spec.

- [x] **Step 1: Write tool registration and behavior tests**

```python
async def test_only_granted_interaction_tools_are_registered():
    tools = build_interaction_tools(
        grants={"interaction.capabilities.list/1": "1"},
        installation_id="install-1",
        conversation_id="chat-1",
        business_call=business_call,
    )
    assert set(tools) == {"interaction_component_catalog"}


async def test_create_reports_field_paths_without_side_effects():
    response = await tools["interaction_card_create"](
        task_key="question", interaction_revision=1,
        component_type="single_select", card={"options": []},
    )
    assert '"error":"INVALID_INTERACTION_REQUEST"' in response.content[0]["text"]
```

Also cover default `card_only`, catalog filtering, status scoping, cancellation keys, unexpected fields, public-safe uncertain errors, and toolkit restoration after success/failure.

- [x] **Step 2: Run and verify RED**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/runner/test_interaction_tools.py -q`

Expected: fail for missing tool module/registration.

- [x] **Step 3: Implement tools with detailed model-facing documentation**

Tool docstrings must state when to use/not use each capability, require a catalog detail lookup before create, describe every argument/default, distinguish recommended/default, explain text-only versus ID+text options, and explain success/failure evidence.

- [x] **Step 4: Bind interaction tools alongside AIGC tools**

Build tools only from the installation grant and current conversation identity. Nest scoped toolkit binders so both families coexist and both restore the original toolkit after completion, exception, or cancellation.

- [x] **Step 5: Run focused and existing orchestration tests**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/runner/test_interaction_tools.py tests/unit/app/runner/test_aigc_tools.py tests/unit/app/workspace -q`

Expected: pass without changing existing AIGC behavior.

### Task 4: Add REST restoration, submission, events, and trusted user input

**Files:**
- Create: `src/qwenpaw/app/super_experts/interaction_events.py`
- Create: `tests/unit/routers/test_super_expert_interactions.py`
- Modify: `src/qwenpaw/app/routers/super_expert_platform.py`
- Modify: `src/qwenpaw/app/super_experts/composition.py`
- Modify: `src/qwenpaw/app/super_experts/service.py` only if shared routing helpers are required

**Interfaces:**
- Produces: `GET /super-expert-platform/interactions`, `POST /super-expert-platform/interactions/{interaction_id}/submit`, and `super_expert_interaction` runtime events.
- Produces a submission response with the updated card and trusted `user_input` text.

- [x] **Step 1: Write route tests first**

Test access control, alias resolution, tenant/installation isolation, restore payload, stale version, invalid option, required supplement, duplicate submit, SSE payload, and trusted server-derived user input. Assert the route does not invoke Agent, model, or billing execution.

```python
async def test_submit_returns_server_resolved_user_input(client, card):
    response = await client.post(
        f"/super-expert-platform/interactions/{card.interaction_id}/submit",
        json={"version": 1, "selected": [{"id": "a"}],
              "supplement": "", "idempotency_key": "submit-1"},
    )
    assert response.status_code == 200
    assert response.json()["user_input"] == "甲"
```

- [x] **Step 2: Run and verify RED**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/routers/test_super_expert_interactions.py -q`

Expected: 404 or import failure because routes/events do not exist.

- [x] **Step 3: Implement read and submit routes**

Resolve chat ownership before reading a card. Submit through `InteractionService`, publish a separate interaction envelope, and never manufacture AIGC binding fields.

- [x] **Step 4: Return trusted ordinary user input**

Generate customer-readable text only from the persisted, server-resolved answer and return it immediately. The endpoint must not call or wait for an Agent/model. The client passes this value into the original chat submit entry so the existing session, selected model, billing, persistence, and streaming behavior remain unchanged.

- [x] **Step 5: Run route, capability, and AIGC regression tests**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/routers/test_super_expert_interactions.py tests/unit/routers/test_super_expert_platform.py tests/unit/app/super_experts tests/integration/test_super_expert_aigc_workflow.py -q`

Expected: pass.

### Task 5: Build the Client API, projection, and adaptive choice card

**Files:**
- Modify: `console/src/api/modules/superExpertPlatform.ts`
- Create: `console/src/pages/Chat/components/SuperExpertInteractionCards.tsx`
- Create: `console/src/pages/Chat/components/SuperExpertInteractionCard.tsx`
- Create: `console/src/pages/Chat/components/SuperExpertInteractionCard.module.less`
- Create: `console/src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`

**Interfaces:**
- Consumes: persisted cards and `super_expert_interaction` events.
- Produces: normalized card projections, `onBlockingChange(blocked: boolean)`, and `onContinuationComplete()` callbacks.

- [x] **Step 1: Write real component behavior tests**

Cover single/multi selection, recommended versus selected, default values, min/max validation, optional/required supplement, long text wrapping, `auto/list/grid`, keyboard focus, disabled/submitting/submitted/expired states, duplicate click prevention, REST+SSE merge, and retry after API failure.

```tsx
it("does not treat the recommended option as selected", () => {
  render(<SuperExpertInteractionCard projection={recommendedButNotDefault} />);
  expect(screen.getByText("AI 推荐")).toBeVisible();
  expect(screen.getByRole("radio", { name: /甲/ })).not.toBeChecked();
});
```

- [x] **Step 2: Run and verify RED**

Run: `./node_modules/.bin/vitest run src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`

Expected: fail because components/API types do not exist.

- [x] **Step 3: Implement typed API and event projection**

Define discriminated TypeScript unions matching Server v1. Restore via REST, merge live events by interaction ID/version, and keep REST authoritative when SSE is missing.

- [x] **Step 4: Implement accessible adaptive UI**

Use semantic radio/checkbox inputs, full wrapped text, top-aligned controls, autosizing supplement, `aria-live` errors, `focus-visible`, hover-capable media query, theme tokens, reduced motion, and mobile single-column fallback. Do not truncate decision text.

- [x] **Step 5: Run component tests and type checking**

Run: `./node_modules/.bin/vitest run src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`

Run: `./node_modules/.bin/tsc -b --noEmit`

Expected: pass.

### Task 6: Integrate cards with the Chat composer

**Files:**
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/ChatPage.test.tsx`
- Modify: `console/src/components/WorkbenchInput/index.tsx`
- Modify: `console/src/components/WorkbenchInput/WorkbenchInput.test.tsx`
- Modify: `console/src/components/WorkbenchInput/index.module.less`

**Interfaces:**
- Consumes: active blocking state and trusted user-input callback from Task 5.
- Produces: complete composer lock and ordinary chat submission after a card is accepted.

- [x] **Step 1: Write failing integration tests**

Assert an active `PENDING + card_only` card disables textarea, attachment, drag/drop, voice, send, skill/agent toolbar actions, and displays “请先完成上方选择”. Assert no lock before REST creation succeeds. Assert submit completion sends returned `user_input` once through the existing runtime input submit function and restores the composer after card state changes.

- [x] **Step 2: Run and verify RED**

Run: `./node_modules/.bin/vitest run src/components/WorkbenchInput/WorkbenchInput.test.tsx src/pages/Chat/ChatPage.test.tsx`

Expected: fail on missing card integration and incomplete toolbar lock.

- [x] **Step 3: Implement the lock and ordinary input dispatch**

Pass the blocking state into `WorkbenchInput.disabled`, prevent every message-producing handler, and keep stop-generation available only for an already running turn. After successful submission, update the card projection and call the same AgentScope runtime input submit function used by ordinary text messages. Do not remount the runtime or add a card-specific Agent execution path.

- [x] **Step 4: Run Chat regression tests and type checking without packaging**

Run: `./node_modules/.bin/vitest run src/components/WorkbenchInput/WorkbenchInput.test.tsx src/pages/Chat/ChatPage.test.tsx src/pages/Chat/components/SuperExpertAigcTaskCard.test.tsx src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`

Run: `./node_modules/.bin/tsc -b --noEmit`

Expected: tests and type checking pass; existing AIGC cards still render. Do not
run a production build before the user's explicit release confirmation.

### Task 7: Migrate LuYu to the live interaction catalog

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/AGENTS.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-operator/SKILL.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-operator/references/follow-up-questions.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-traffic-diagnosis/SKILL.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-traffic-diagnosis/references/business-rules.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-content-director/SKILL.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-content-director/references/business-rules.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/manifest.template.json`
- Modify generated turn packets under `skills/luyu-operator/references/turn-packets/`
- Modify/add focused tests under `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/tests/`

**Interfaces:**
- Consumes: live `interaction_component_catalog` and `interaction_card_create` tools.
- Produces: Agent rules that convert every actual closed-choice prompt to a real DClaw card and preserve open-text questions.

- [x] **Step 1: Write behavior-contract tests before changing rules**

Tests should parse the effective Agent/Skill packet inputs and assert the decision contract: closed choices require live catalog + successful card creation; open questions remain text; failures prohibit fake/text fallback; submissions are not re-asked; explicit S2 candidates and A/B/C/D production modes route to correct component types.

- [x] **Step 2: Run and verify RED**

Run: `python3 -m pytest tests/test_interaction_card_policy.py tests/test_turn_packets.py tests/test_package_structure.py -q`

Expected: fail because the interaction rules/capabilities are absent.

- [x] **Step 3: Update authoritative rules and explicit choice sites**

Add one shared closed-choice policy at the global/entry boundary, then change explicit S2 and production-mode instructions so they generate card payloads instead of visible letter/number prompts. Preserve customer-visible confidentiality and incremental-question rules.

- [x] **Step 4: Update manifest source without packaging**

Add `interaction: "1"` and the three capability declarations, recompute the capability digest using DClaw's authoritative function, but do not bump/release/sign/build a ZIP.

- [x] **Step 5: Regenerate turn packets and run Agent tests**

Run: `python3 scripts/build_turn_packets.py`

Run: `python3 -m pytest tests -q`

Run: `python3 scripts/validate_workspace.py --workspace .`

Expected: all tests pass and generated packets contain the updated rules exactly once through their normal source inclusion.

### Task 8: Complete local cross-system verification

**Files:**
- Create: `docs/super-expert-interaction-agent-tools.md`
- Modify: `docs/super-expert-platform-v1.md`
- Add or modify integration tests under `tests/integration/`
- Add local validation notes under `docs/superpowers/reports/`

**Interfaces:**
- Proves the Server contract, Client UI, and LuYu declarations agree without producing release artifacts.

- [x] **Step 1: Write the public API documentation from the authoritative contract**

Document the decision index, every field/default/limit, request/response schemas, correct/error examples, stable errors, idempotency, replacement, submission, event, versioning, compatibility, and responsibility boundary. Cross-check field names against JSON Schema output.

- [x] **Step 2: Add end-to-end local integration coverage**

Use a real in-process interaction repository, platform service, REST client, and event bus. Assert catalog → create → restore → composer-blocking payload → submit → trusted `user_input` → submitted restore, with no Agent/model call inside the submit route.

- [x] **Step 3: Run Server test suites**

Run: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest tests/unit/app/super_experts tests/unit/app/runner/test_interaction_tools.py tests/unit/app/runner/test_aigc_tools.py tests/unit/routers/test_super_expert_interactions.py tests/unit/routers/test_super_expert_platform.py tests/integration/test_super_expert_interactions.py tests/integration/test_super_expert_aigc_workflow.py -q`

Then run the full Server suite if the focused suite is green: `'/Users/moxi/Desktop/codex space/dclaw-server/.venv/bin/python' -m pytest -q`.

- [x] **Step 4: Run Client test suites without a production build**

Run: `./node_modules/.bin/vitest run src/pages/Chat src/components/WorkbenchInput`

Run: `./node_modules/.bin/tsc -b --noEmit`

Do not run `vite build` before the user's explicit release confirmation.

- [x] **Step 5: Run LuYu full validation**

Run from LuYu source: `python3 -m pytest tests -q` and `python3 scripts/validate_workspace.py --workspace .`.

- [x] **Step 6: Perform local smoke and inspect all diffs**

Start only local Server/Client processes if the repository provides a non-production fixture configuration. Exercise long-text single select, bounded multi select with optional supplement, required supplement error, replacement, card-only composer lock, ordinary-input submission, and reload persistence. Record exact commands and observed results. Run `git diff --check`, inspect Server and Client `git status`, and verify the main Client checkout's pre-existing dirty files are unchanged.

- [x] **Step 7: Stop before release operations**

Do not commit, push, package, build an image, or deploy. Deliver the local test report and exact remaining release steps for the user's later confirmation.
