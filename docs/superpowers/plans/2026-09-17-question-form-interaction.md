# Question Form Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `question_form` basic interaction component to DClaw and make LuYu route every customer question through the correct interaction card.

**Architecture:** Extend the existing discriminated interaction contract and repository rather than creating a second subsystem. The server validates and persists trusted question answers, the client renders a dedicated full-width form inside the existing card shell, and LuYu uses the live catalog decision boundary to choose selection versus open-question cards.

**Tech Stack:** Python 3, Pydantic v2, FastAPI, pytest, React, TypeScript, Vitest, Testing Library, Less, Markdown Agent skills.

**Spec:** `docs/superpowers/specs/2026-09-17-question-form-interaction-design.md`

## Global Constraints

- `question_form` is additive to interaction contract version `1`.
- `card_only` remains the default input policy.
- Each question item renders as one full-width row.
- `required` defaults to `true`; `max_length` defaults to `2000` and is limited to `1..5000`.
- The server resolves IDs/questions and never trusts client-supplied labels.
- Closed questions use selection cards; only non-enumerable questions use `question_form`.
- Do not push, commit, package, build an image, or deploy production in this plan.

---

### Task 1: Server contract and catalog

**Files:**
- Modify: `src/qwenpaw/app/super_experts/interaction_contract.py`
- Test: `tests/unit/app/super_experts/test_interaction_contract.py`

**Interfaces:**
- Produces: `QuestionFormCard`, `InteractionQuestionItem`, `InteractionResolvedAnswer`, and `InteractionComponentType.QUESTION_FORM`.
- Produces: `validate_card("question_form", card)` and detailed catalog schema/example.

- [ ] **Step 1: Write failing contract tests**

```python
def test_question_form_catalog_exposes_strict_defaults():
    component = build_interaction_catalog(["question_form"])["components"][0]
    assert component["defaults"] == {
        "input_policy": "card_only",
        "items[].placeholder": "请输入回答",
        "items[].required": True,
        "items[].max_length": 2000,
    }
    assert component["create_example"]["component_type"] == "question_form"

def test_question_form_rejects_duplicate_question_and_unknown_fields():
    with pytest.raises(InteractionValidationError):
        validate_card("question_form", {
            "title": "请回答",
            "items": [
                {"question": "同一个问题"},
                {"question": "同一个问题", "unexpected": True},
            ],
        })
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/app/super_experts/test_interaction_contract.py -q`

Expected: failures because `question_form` is unknown and its models/defaults do not exist.

- [ ] **Step 3: Implement the minimal strict models and catalog branch**

```python
class InteractionQuestionItem(_StrictFrozenModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=1000)
    placeholder: str = Field(default="请输入回答", min_length=1, max_length=200)
    required: bool = True
    max_length: int = Field(default=2000, ge=1, le=5000)

class QuestionFormCard(_StrictFrozenModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    items: tuple[InteractionQuestionItem, ...] = Field(min_length=1, max_length=20)
```

Add preflight uniqueness checks for non-empty IDs and normalized question
texts, select `QuestionFormCard` from `validate_card`, and add an unambiguous
catalog summary, use/do-not-use copy, defaults, schema, and create example.

- [ ] **Step 4: Run contract tests and verify GREEN**

Run: `uv run pytest tests/unit/app/super_experts/test_interaction_contract.py -q`

Expected: all contract tests pass.

### Task 2: Trusted persistence and REST submission

**Files:**
- Modify: `src/qwenpaw/app/super_experts/interaction_cards.py`
- Modify: `src/qwenpaw/app/routers/super_expert_platform.py`
- Test: `tests/unit/app/super_experts/test_interaction_cards.py`
- Test: `tests/unit/routers/test_super_expert_interactions.py`
- Test: `tests/integration/test_super_expert_interactions.py`

**Interfaces:**
- Consumes: `QuestionFormCard` and persisted item IDs/questions from Task 1.
- Produces: component-discriminated `selected/supplement` or `answers` submit payloads.
- Produces: trusted `InteractionAnswer.answers` in persisted card order.

- [ ] **Step 1: Write failing repository tests**

```python
def test_question_form_submission_resolves_ids_and_optional_null(service):
    card = _create(service, _question_request())
    result = service.submit(
        interaction_id=card.interaction_id,
        installation_id="installation-1",
        conversation_id="conversation-1",
        version=1,
        answers=[{"id": "scope", "value": "  空调\n冰箱  "}],
        idempotency_key="submit-question",
    )
    assert [item.model_dump() for item in result.answer.answers] == [
        {"id": "scope", "question": "服务范围？", "value": "空调\n冰箱"},
        {"id": None, "question": "其他情况？", "value": None},
    ]

@pytest.mark.parametrize("answers,code", [
    ([], "REQUIRED_ANSWER_MISSING"),
    ([{"id": "unknown", "value": "x"}], "INVALID_ANSWER_REFERENCE"),
    ([{"id": "scope", "value": "123456"}], "ANSWER_TOO_LONG"),
])
def test_question_form_rejects_invalid_answers(service, answers, code):
    with pytest.raises(InteractionError, match=code):
        service.submit(..., answers=answers, idempotency_key=code)
```

- [ ] **Step 2: Run repository tests and verify RED**

Run: `uv run pytest tests/unit/app/super_experts/test_interaction_cards.py -q`

Expected: failures because submit accepts only selection fields.

- [ ] **Step 3: Implement component-discriminated answer resolution**

Change repository submission to accept optional `selected`, `supplement`, and
`answers`, include the active branch in the idempotency digest, reject fields
from the wrong branch, resolve answer references against the stored card, fill
missing optional items with `null`, and construct a discriminated trusted
answer without changing state-transition behavior.

- [ ] **Step 4: Run repository tests and verify GREEN**

Run: `uv run pytest tests/unit/app/super_experts/test_interaction_cards.py -q`

Expected: all repository tests pass.

- [ ] **Step 5: Write failing REST and integration tests**

```python
response = client.post(
    f"/super-expert-platform/interactions/{interaction_id}/submit",
    json={
        "version": 1,
        "answers": [{"id": "scope", "value": "空调维修"}],
        "idempotency_key": "rest-question-submit",
    },
)
assert response.status_code == 200
assert response.json()["interaction"]["answer"]["answers"][0]["question"] == "服务范围？"
```

Add negative cases proving choice payloads reject `answers`, question forms
reject `selected/supplement`, and stable answer errors return HTTP 422.

- [ ] **Step 6: Run REST tests and verify RED**

Run: `uv run pytest tests/unit/routers/test_super_expert_interactions.py tests/integration/test_super_expert_interactions.py -q`

Expected: the question payload is rejected by the old request model.

- [ ] **Step 7: Implement the strict REST union and error mapping**

Use optional fields plus a model validator on `InteractionSubmitRequest` so
the persisted component remains authoritative in the repository. Map
`REQUIRED_ANSWER_MISSING`, `ANSWER_TOO_LONG`, and
`INVALID_ANSWER_REFERENCE` to HTTP 422 and pass `answers` into submission.

- [ ] **Step 8: Run REST tests and verify GREEN**

Run: `uv run pytest tests/unit/routers/test_super_expert_interactions.py tests/integration/test_super_expert_interactions.py -q`

Expected: all tests pass.

### Task 3: Agent tool schema and runner exposure

**Files:**
- Modify: `src/qwenpaw/app/workspace/interaction_tools.py`
- Modify: `src/qwenpaw/app/runner/runner.py`
- Test: `tests/unit/app/runner/test_interaction_tools.py`

**Interfaces:**
- Consumes: `question_form` catalog/create contract.
- Produces: Agent-callable `component_type: Literal["single_select", "multi_select", "question_form"]` and descriptions that route open questions correctly.

- [ ] **Step 1: Write failing runner/tool-schema tests**

```python
catalog = await tools["interaction_component_catalog"](["question_form"])
assert catalog["components"][0]["component_type"] == "question_form"
assert "无法预先列全" in schemas["interaction_card_create"]["description"]
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/unit/app/runner/test_interaction_tools.py -q`

Expected: the Literal/schema and descriptions omit `question_form`.

- [ ] **Step 3: Extend tool annotations and routing guidance**

Add `question_form` to exact type annotations and describe: complete choices
use the matching select component; non-enumerable free-text facts use
`question_form`; creation always follows a detailed catalog read.

- [ ] **Step 4: Run and verify GREEN**

Run: `uv run pytest tests/unit/app/runner/test_interaction_tools.py -q`

Expected: all tool tests pass.

### Task 4: Client API projection and question-form rendering

**Files:**
- Modify: `console/src/api/modules/superExpertPlatform.ts`
- Modify: `console/src/pages/Chat/components/SuperExpertInteractionCard.tsx`
- Modify: `console/src/pages/Chat/components/SuperExpertInteractionCard.module.less`
- Modify: `console/src/pages/Chat/components/SuperExpertInteractionCards.tsx`
- Test: `console/src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`
- Test: `console/src/pages/Chat/components/SuperExpertInteractionCards.test.tsx`

**Interfaces:**
- Consumes: REST `question_form` card and trusted `answer.answers` shapes.
- Produces: `answers: Array<{id?: string; question?: string; value: string | null}>` submit payload.

- [ ] **Step 1: Write failing component behavior tests**

```tsx
it("renders each question as a full-width row and focuses missing required answers", async () => {
  render(<SuperExpertInteractionCard projection={questionForm()} onSubmit={vi.fn()} />);
  expect(screen.getAllByTestId("question-item")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
  expect(screen.getByLabelText("服务范围？")).toHaveFocus();
  expect(screen.getByText("请填写此项")).toBeVisible();
});

it("submits trimmed answers and preserves internal newlines", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  render(<SuperExpertInteractionCard projection={questionForm()} onSubmit={onSubmit} />);
  fireEvent.change(screen.getByLabelText("服务范围？"), { target: { value: "  空调\n冰箱  " } });
  fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
    answers: [{ id: "scope", question: "服务范围？", value: "空调\n冰箱" }, expect.anything()],
  })));
});
```

- [ ] **Step 2: Run component tests and verify RED**

Run: `pnpm --dir console vitest run src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`

Expected: TypeScript/component failures because the question projection does not exist.

- [ ] **Step 3: Add discriminated client models and renderer**

Define choice and question projections as a discriminated union. Render a
question branch with one `questionItem` row per item, an auto-growing textarea,
inline required error, stable character count, read-only submitted answers,
and `提交回答` copy. Keep the existing choice branch behavior unchanged.

- [ ] **Step 4: Add full-width, responsive, hover, focus, dark-mode styles**

Use the existing CSS variables and card tokens. `.questionItems` is a one-column
grid for every width; `.questionItem` uses `overflow-wrap:anywhere`; textarea
uses `width:100%`, bounded auto-growth, and no resize handle. Hover must not
transform or reflow the row.

- [ ] **Step 5: Run component tests and verify GREEN**

Run: `pnpm --dir console vitest run src/pages/Chat/components/SuperExpertInteractionCard.test.tsx`

Expected: all component tests pass.

- [ ] **Step 6: Write failing orchestration/API payload test**

Add a `question_form` REST fixture, fill it, submit, and assert
`submitInteraction` receives `answers` without `selected` or `supplement`.

- [ ] **Step 7: Run orchestration test and verify RED**

Run: `pnpm --dir console vitest run src/pages/Chat/components/SuperExpertInteractionCards.test.tsx`

Expected: old projection/submit mapping sends selection fields.

- [ ] **Step 8: Implement projection and payload dispatch**

Project each record by `component_type`; send the exact branch through the API;
keep one stable idempotency key per interaction/version and send the returned
trusted text through the existing ordinary chat input path.

- [ ] **Step 9: Run client interaction tests and type-check**

Run: `pnpm --dir console vitest run src/pages/Chat/components/SuperExpertInteractionCard.test.tsx src/pages/Chat/components/SuperExpertInteractionCards.test.tsx src/components/WorkbenchInput/WorkbenchInput.test.tsx`

Run: `pnpm --dir console exec tsc --noEmit`

Expected: all tests and type-check pass.

### Task 5: Generic interaction copy and accessibility

**Files:**
- Modify: `console/src/components/WorkbenchInput/index.tsx`
- Modify: `console/src/components/WorkbenchInput/WorkbenchInput.test.tsx`
- Modify: `console/src/pages/Chat/components/SuperExpertInteractionCards.tsx`
- Test: `console/src/components/WorkbenchInput/WorkbenchInput.test.tsx`

**Interfaces:**
- Produces: component-neutral lock and recovery copy for every basic interaction card.

- [ ] **Step 1: Change the existing test expectation first**

```tsx
expect(screen.getByText("请先完成上方交互卡片，提交后即可继续输入")).toBeVisible();
```

Also assert the card collection region is labelled `基础交互` and load errors
say `交互卡片加载失败`.

- [ ] **Step 2: Run and verify RED**

Run: `pnpm --dir console vitest run src/components/WorkbenchInput/WorkbenchInput.test.tsx src/pages/Chat/components/SuperExpertInteractionCards.test.tsx`

Expected: current copy still says `选择卡片`.

- [ ] **Step 3: Implement component-neutral copy**

Replace only the affected user-visible strings. Do not alter locking semantics.

- [ ] **Step 4: Run and verify GREEN**

Run the same Vitest command; expected all pass.

### Task 6: Complete Agent documentation and LuYu routing

**Files:**
- Modify: `docs/super-expert-interaction-agent-tools.md`
- Modify: `docs/super-expert-platform-v1.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/README.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-operator/references/follow-up-questions.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-traffic-diagnosis/SKILL.md`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/skills/luyu-traffic-diagnosis/references/nodes/S0.md`
- Test: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-dclaw-agent/tests/test_interaction_card_policy.py`

**Interfaces:**
- Consumes: the live `question_form` catalog and create schema.
- Produces: deterministic LuYu routing: select when enumerable, question form otherwise, no customer question only in prose.

- [ ] **Step 1: Write failing LuYu behavior tests**

Add executable policy scenarios proving:

```python
assert route_question(complete_options=["更多订单", "品牌认知"]) == "single_select"
assert route_question(complete_options=None, free_text=True) == "question_form"
assert route_multiple_open_questions(3) == {"component_type": "question_form", "item_count": 3}
```

Use the repository's existing policy-test harness rather than source-text grep.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_interaction_card_policy.py -q`

Expected: open questions are still allowed as normal conversation.

- [ ] **Step 3: Update LuYu instructions and examples**

State the three-way decision boundary, catalog-first rule, maximum three open
items, no prose fallback, and separate sequencing for mixed component types.
For the S0 screenshot case, goal and operating status are selection questions
when LuYu can form complete options; only remaining non-enumerable facts use
`question_form`.

- [ ] **Step 4: Expand the public Agent API document**

Document every field/default/limit, positive and negative examples, submit and
trusted answer schemas, stable errors, persistence/retry semantics, and the
DClaw-versus-Agent responsibility boundary. Keep existing selection semantics
unchanged.

- [ ] **Step 5: Run LuYu tests and workspace validation**

Run: `python -m pytest tests/test_interaction_card_policy.py tests/test_package.py -q`

Run: `python scripts/validate_workspace.py`

Expected: all tests and validation pass.

### Task 7: Local regression and runtime smoke test

**Files:**
- Modify only if a failing test exposes a defect in files already listed.
- Record results in: `docs/superpowers/reports/2026-09-17-basic-interaction-local-validation.md`

**Interfaces:**
- Verifies all earlier tasks together without packaging or deployment.

- [ ] **Step 1: Run focused server suite**

Run: `uv run pytest tests/unit/app/super_experts/test_interaction_contract.py tests/unit/app/super_experts/test_interaction_cards.py tests/unit/app/runner/test_interaction_tools.py tests/unit/routers/test_super_expert_interactions.py tests/integration/test_super_expert_interactions.py -q`

Expected: all pass.

- [ ] **Step 2: Run full client suite and type-check**

Run: `pnpm --dir console vitest run`

Run: `pnpm --dir console exec tsc --noEmit`

Expected: all pass with no TypeScript errors.

- [ ] **Step 3: Run full LuYu suite**

Run: `python -m pytest -q`

Run: `python scripts/validate_workspace.py`

Expected: all pass.

- [ ] **Step 4: Restart only the local 18088 development stack**

Rebuild/restart the local source-mounted development services only if required
for changed source to load. Do not build a distributable image or package.

- [ ] **Step 5: Exercise the real local API and browser flow**

Create one `question_form` through the real Agent capability path, verify every
item occupies one row, required validation/focus works, submit persists the
trusted answer, the composer unlocks, and the returned values enter the same
ordinary chat submission path as typed text. Then create a selection question and verify the pre-existing flow is
unchanged.

- [ ] **Step 6: Record exact local evidence**

Append commands, pass counts, local URL, and any known baseline-only failures
to the existing validation report. Do not mark production or packaging as
completed.
