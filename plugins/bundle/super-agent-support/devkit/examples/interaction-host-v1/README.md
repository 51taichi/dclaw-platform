# Direct Host interaction example

`single-select-success.json` contains a complete successful `single_select`
create call and its persisted Host result. The `trusted_scope_example` values
are illustrative Host context, never caller-supplied arguments.

1. Declare and obtain grants for `interaction.capabilities.list/1` and
   `interaction.card.create/1`. Call
   `await host.call("interaction.capabilities.list/1", {"component_types": ["single_select"]})`.
   An empty or omitted `component_types` returns only the compact index.
   The filtered response returns the complete, current card JSON Schema at
   `components[0].schema`, plus `defaults` and `create_example`. Validate the
   draft `request.card` against that exact Schema and check business invariants
   before creating. `GET /api/super-agent-support/component-registry` lists
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
