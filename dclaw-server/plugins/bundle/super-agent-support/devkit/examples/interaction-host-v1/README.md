# Direct Host interaction example

`single-select-success.json` contains a complete successful `single_select`
create call and its persisted Host result. The `trusted_scope_example` values
are illustrative Host context, never caller-supplied arguments.

`devkit/interaction_card_api_demo.py` is an executable reference for the two
direct Host calls. `create_card` uses the same boundary for `single_select`,
`multi_select`, `question_form`, and `file_selector`; its required
`check_business` callback checks each Agent's own fixed business fields.
The `create_single_select` wrapper below shows option ID and order checks.
A signed Agent can adapt its shared card module to this boundary after one
model call has produced the business reply and optional card suggestion:

```python
from devkit.interaction_card_api_demo import create_single_select

interaction_id = await create_single_select(
    host,
    task_key="customer-choice",
    interaction_revision=1,
    card={
        "title": "请选择最贴近的一项",
        "options": [
            {"id": "option-a", "text": "选项甲"},
            {"id": "option-b", "text": "选项乙"},
        ],
    },
    expected_title="请选择最贴近的一项",
    expected_option_ids=["option-a", "option-b"],
    idempotency_key="customer-choice-rev-1",
)
# Only now may runtime.complete commit the customer message and card reference.
```

The function calls `interaction.capabilities.list/1` with the exact component
type, checks the fixed business question and IDs, calls
`interaction.card.create/1`, and requires the returned
`interaction` and `interaction.card.receipt/1` to match. It raises on any
failure. The calling Agent must keep the business state, stable key, revision,
replacement rules and `runtime.complete/fail` transaction handling. The
Support Plugin validates the card against its published complete Schema at
the create boundary. The signed Agent need not carry `jsonschema` for this
platform check. Copy or adapt the reference in each signed Agent; a Developer
Pack file is not automatically importable by the sealed runtime.

1. Declare and obtain grants for `interaction.capabilities.list/1` and
   `interaction.card.create/1`. Call
   `await host.call("interaction.capabilities.list/1", {"component_types": ["single_select"]})`.
   An empty or omitted `component_types` returns only the compact index.
   The filtered response returns the complete, current card JSON Schema at
   `components[0].schema`, plus `defaults` and `create_example`. Check the
   Agent's business invariants before creating; the Host checks the draft
   `request.card` against that exact Schema during create. On rejection, use
   the same model turn's text fallback. `GET /api/super-agent-support/component-registry` lists
   local-helper public components; it is not the interaction-card catalog.
2. Call `await host.call("interaction.card.create/1", create_call.arguments)`
   with a stable `idempotency_key` for the same installation, task, `task_key`,
   revision and payload. The Host supplies tenant, installation and task scope.
   `request.input_policy` defaults to `card_only`, which blocks ordinary text
   input while the card is pending. `card_or_text` and `concurrent` keep text
   input available; neither turns free text into proof of card submission.
   A changed question, option set or input policy needs a new
   `interaction_revision` and operation key. Use `replaces_interaction_id`
   when replacing an active blocking card. Reusing a key with different input
   fails with `IDEMPOTENCY_CONFLICT`.
3. On a new creation, require `interaction.status=PENDING`, a real
   `interaction.interaction_id`, and `receipt.contract=interaction.card.receipt/1`,
   `receipt.action=created`, `receipt.status=PENDING`. Compare the receipt's
   interaction ID, trusted installation and conversation IDs, task key,
   revision and version with the returned interaction. Its `event_id` must
   match the `create` transition. A later `session.context.interaction_receipts`
   may contain the same `created` receipt; correlate by `event_id` and
   `interaction_id`. The Host may return the current non-PENDING interaction
   on an idempotent replay after submission, while the original `created`
   receipt remains PENDING. Read current status instead of presenting that
   replay as a newly created card.

The outer Host request and response schemas are in
`schemas/interaction-capabilities-list-v1/` and
`schemas/interaction-card-create-v1/`. The dynamic `card` member is validated
against the selected live `components[].schema`; the outer create schema does
not replace it. The independently versioned receipt schema is in
`schemas/interaction-card-receipt-v1/`.

For a pre-publication regression, validate the included `create_example.card`
against `fixtures/interaction-host-v1/single-select-live-catalog.json` and
reject cards missing `title` or carrying unknown fields. This fixture contains
real `$defs` and nested `$ref` nodes. `devkit/validate_live_card.py` shows
complete Draft 2020-12 validation for developer tests; it requires
`jsonschema>=4.20,<5` in that test environment. A custom keyword whitelist is
insufficient even if it accepts one version of the catalog. Repeat the check
against the target Host's detailed catalog before publication. The Support
Plugin performs the authoritative create-time check. Keep option IDs, order
and business state checks separate from structural Schema validation.

The Skill's release gate must run the API reference or an equivalent shared
Agent implementation against the real catalog fixture, invalid cards and a
bad `created` receipt. It must also check that the target instance's detailed
catalog accepts its own `create_example.card`. A passing offline mock cannot
prove that a customer click and same-task continuation work; verify those in
the client after activation.
