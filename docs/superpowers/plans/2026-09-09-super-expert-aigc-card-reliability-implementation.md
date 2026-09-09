# Super Expert AIGC Card Reliability Implementation Plan

> **For Codex:** Execute this plan test-first. Preserve the super-expert boundary: the model owns business decisions and customer wording; trusted code owns identity, persistence, platform contracts, receipts, and session isolation.

**Goal:** Make valid Luyu S9 AIGC requests reliably create the correct conversation-bound card, prevent stale canvases from leaking into another conversation, and expose actionable platform failures without fabricating success.

**Architecture:** DClaw publishes an exact executable workflow catalog and applies a narrow transport canonicalizer before compilation. Luyu selects the business workflow from that catalog and forwards it unchanged in meaning. DClaw returns the only authoritative creation receipt. Generic workspace artifact delivery excludes AIGC studio internals; AIGC cards are rendered only from fully bound material-task receipts.

**Tech Stack:** Python 3, Pydantic, pytest/pytest-asyncio, DClaw super-expert capability bus, configured Luyu runtime.

---

## Task 1: Publish an exact workflow-node contract

**Files:**
- Modify: `src/qwenpaw/aigc/workflow_contract.py`
- Modify: `src/qwenpaw/app/aigc/models.py`
- Modify: `src/qwenpaw/app/aigc/capability_service.py`
- Test: `tests/unit/app/aigc/test_shared_services.py`
- Test: `tests/integration/test_super_expert_aigc_workflow.py`

1. Add failing tests asserting each projected node declares its allowed customer actions plus a closed parameter contract with types, enums/ranges, and safe defaults where one exists.
2. Run the focused tests and confirm the catalog currently lacks these fields.
3. Extend `NodeRegistration` and `WorkflowNodeCapability` with serializable `parameter_schema` and input guidance needed by a model to form a valid request.
4. Define canonical workflow-level parameter names (`aspect_ratio`, `resolution`, `count`, `duration_seconds`, `generate_audio`, modes) once in the node registry; do not copy provider-private payload names into the workflow contract.
5. Project these fields through `project_workflow_capability_catalog` and rerun the focused tests.

## Task 2: Canonicalize only safe transport aliases

**Files:**
- Modify: `src/qwenpaw/aigc/workflow_compiler.py`
- Test: `tests/unit/aigc/test_workflow_compiler.py`

1. Add failing tests for whitespace/case normalization and the explicit resolution aliases `1080x1920`/`1920x1080 -> 1080P` and `720x1280`/`1280x720 -> 720P`.
2. Add tests proving prompts, selected models, capabilities, graph topology, asset IDs, and unsupported values are not changed.
3. Introduce a pure `canonicalize_workflow_blueprint` step before scalar validation. It may normalize only the documented transport aliases and omit empty optional values with registry defaults.
4. Do not reinterpret `customer_action`, invent assets, select models, or repair business decisions. Invalid unsupported values still return the existing stable platform error.
5. Run compiler and super-expert integration tests.

## Task 3: Prevent shared AIGC workspace leakage

**Files:**
- Modify: `src/qwenpaw/app/artifact_filter.py`
- Modify: `src/qwenpaw/app/channels/console/channel.py`
- Test: `tests/unit/app/test_artifact_filter.py`
- Test: `tests/unit/channels/test_console.py`

1. Add failing tests showing `aigc_studio/**` files are never generic user-task artifacts, including when they are the only changed images.
2. Add a two-session console test: a file created under an old canvas cannot trigger a delivery card in the current conversation.
3. Exclude the complete `aigc_studio` internal namespace at scan/filter time. Keep normal session-owned deliverables working.
4. Require AIGC presentation to come from the super-expert material-task/card projection, never from recursive workspace modification detection.
5. Run artifact and console tests.

## Task 4: Keep creation transactional and receipt-bound

**Files:**
- Modify: `src/qwenpaw/app/super_experts/service.py` only if failing tests reveal a gap
- Modify: `src/qwenpaw/app/super_experts/aigc_tasks.py` only if failing tests reveal a gap
- Test: `tests/integration/test_super_expert_aigc_workflow.py`
- Test: `tests/unit/routers/test_super_expert_platform.py`

1. Add tests that an invalid workflow creates no material task/canvas/card and that a successful response contains the exact installation, conversation, agent task, content revision, material task, canvas, workflow, and output-node bindings.
2. Add idempotency tests: replaying the same event returns the same receipt; another conversation cannot resolve or mutate it.
3. Run tests before implementation. If existing code passes, record that the receipt boundary is already sufficient and make no production change.
4. If a gap exists, make the smallest transactional fix and rerun the tests.

## Task 5: Tighten Luyu S9 request and reply semantics

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next/config/aigc-workflow-contract.json`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next/scripts/luyu_runtime.py`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next/scripts/aigc_workflow.py` only for transport/audit fields, never business validation
- Test: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next/tests/test_workflow_input_guidance.py`
- Test: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next/tests/test_model_workflow_request.py`

1. Add failing tests proving the model sees exact node actions and parameter enums, placeholder asset IDs are explicitly forbidden, and no customer-facing success text is emitted before a real receipt.
2. Add tests that one failed platform call is reported back to the model once, preserves the model's natural reply, records the precise error, and does not claim retries that did not happen.
3. Add tests that a successful task projection must match the current conversation and task revision before `AIGC素材任务` is saved.
4. Update the prompt contract and S9 runtime context. For request-producing passes, tell the model to keep `reply` empty or state only that a request is being submitted; after `aigcWorkflowCreateResult`, the model may describe success or the real failure.
5. Preserve model business choices and final reply verbatim. Do not add a second business validator or rewrite customer text.
6. Run all Luyu S7–S11 and workflow-request tests.

## Task 6: Cover the reported production shapes

**Files:**
- Add: `tests/integration/test_super_expert_aigc_workflow_reliability.py`
- Add/Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next/tests/test_aigc_workflow_reliability.py`

1. Add representative fixtures/tests for:
   - one text-to-image node;
   - two independent text-to-image nodes plus output/review binding;
   - reference-image generation using a real owned asset ID;
   - image-to-video with the correct upstream slot;
   - invalid/missing reference asset with a precise non-success result;
   - concurrent conversations with no task/card/artifact crossover.
2. Run the new tests first and capture failures.
3. Make only the minimal fixes required by those failures.
4. Run the new tests plus the existing AIGC workflow, card-guide, console-channel, and Luyu runtime suites.

## Task 7: Package, deploy locally, and perform live acceptance

**Files:**
- Modify version/release files in `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent-next` according to its existing release script.
- Produce local-signed and production-signed packages using the existing packaging mechanism; do not upload the production package unless explicitly authorized by the existing deployment workflow.

1. Run DClaw server unit/integration tests and Luyu full tests.
2. Build and deploy DClaw from local `main` without pushing remote.
3. Package the next Luyu version twice (local signer and production signer), upload/activate the local package, and retain the production package path for handoff.
4. Run live local acceptance with fresh conversations for the five workflow shapes above. Verify database/state receipts, visible AIGC cards, refresh persistence, and absence of cross-conversation artifacts.
5. Re-run the exact apparel scenario and confirm no Tianmen canvas/artifact can appear.
6. Report concrete package paths, deployed image/version, test counts, and any remaining provider-dependent limitation. Do not claim guaranteed provider generation when an external service is unavailable; guarantee only correct creation/error semantics and isolation.
