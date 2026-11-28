# Direct Host interaction example

`card-type-examples.json` is a machine-checked example for each supported
component. Choose the answer shape from the Agent's actual business question:

| Answer shape | `answer_kind` | `component_type` | Card invariant |
| --- | --- | --- | --- |
| Exactly one from known options | `one_choice` | `single_select` | At least two options |
| Several from known options | `many_choices` | `multi_select` | Bounds include a custom choice when enabled |
| Free-form answer | `open_text` | `question_form` | One `items` entry per customer turn |
| A real local file | `local_file` | `file_selector` | Explicit file count, type and size limits |

The direct Host calls are `interaction.capabilities.list/1` with
`{"component_types": [component_type]}`, followed by
`interaction.card.create/1` with `{"idempotency_key": string, "request": {...}}`.
`request` requires a nonblank `task_key` (at most 160 characters), an integer
`interaction_revision >= 1`, one of the four real `component_type` values,
and a `card` object. New experts set `input_policy="card_or_text"`; the Host
default is `card_only`. An existing card replacement uses
`replaces_interaction_id` (nonempty string). Installation and conversation IDs
come from trusted Host context, never from model output or the create request.

| Card | Required `card` fields | Key type and range constraints |
| --- | --- | --- |
| `single_select` | `title: string`, `options: array` | `title` 1-160 characters; 2-20 options, each with nonblank `text` of at most 500 characters and a stable business `id`. Optional `supplement` is an object. |
| `multi_select` | `title: string`, `options: array` | Same option bounds; `min_selections` is an integer 0-20, `max_selections` an integer 1-20 and no greater than the available options plus one enabled custom choice. `min_selections <= max_selections`. |
| `question_form` | `title: string`, `items: array` | Each item has a nonblank `question` (at most 500 characters) and stable business `id`. The public Host accepts 1-20 items; the new-expert one-question rule requires exactly one item per turn. |
| `file_selector` | `title: string` | `multiple: boolean`; `min_files` and `max_files` are integers 1-20, with `min_files <= max_files` and `max_files=1` when `multiple=false`. MIME types and extensions are string arrays, up to 32 entries each; per-file and total byte limits are positive integers, and total must cover one maximum-size file. |

For selection cards, `supplement.answer_mode="choice"` means custom text is
an answer choice: it must be enabled and optional. It is exclusive with preset
options for `single_select`; for `multi_select` it counts as one selection.
`answer_mode="note"` is only supplemental information. These are the key
boundaries; use the complete current `components[].schema` from the Host for
all fields, formats, optional values and additional-property rejection.

The Agent determines whether answers can be enumerated and whether multiple
choices are valid. A model proposal cannot change that decision. Call
`create_question_card` with the approved `answer_kind`, stable `task_key`,
revision and business validator; it rejects a mismatched component before any
Host call. Internal labels such as `single_select_or_multi_select` are never
API component types. The function defaults to `card_or_text` for new experts.
Its `proposal` contains only `task_key`, `component_type` and `card`;
`idempotency_key`, `interaction_revision` and `input_policy` are runtime-owned
arguments, not model-selected fields. For `file_selector`, separately declare
and obtain the required file-selection and local-helper grants.

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
