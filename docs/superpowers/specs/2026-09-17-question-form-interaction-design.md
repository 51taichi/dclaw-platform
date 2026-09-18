# DClaw Question Form Interaction Design

## Goal

Extend DClaw's version 1 basic interaction catalog with a dedicated
`question_form` component for one or more open-ended customer questions.
Each question is one full-width item containing the question and a customer
answer input. Closed questions remain `single_select` or `multi_select`.

This is an additive component. Existing selection-card requests and answers
keep their current semantics.

## Component decision boundary

The Agent must choose the component before creation:

| Customer action | Component |
|---|---|
| Choose exactly one item from a complete set | `single_select` |
| Choose multiple items from a complete set | `multi_select` |
| Supply free-form facts that cannot be reliably enumerated | `question_form` |

If a turn contains both closed and open questions, the Agent sequences
separate cards according to business dependency. `question_form` does not
embed select fields. This keeps every component contract unambiguous.

## Create contract

`question_form` uses the existing `interaction_card_create` tool and defaults
to `input_policy="card_only"`.

```json
{
  "task_key": "collect-business-context",
  "interaction_revision": 1,
  "component_type": "question_form",
  "input_policy": "card_only",
  "card": {
    "title": "请补充以下信息",
    "description": "请按实际情况填写。",
    "items": [
      {
        "id": "service_scope",
        "question": "你目前主要提供哪些家电维修服务？",
        "description": "例如空调、冰箱、洗衣机等。",
        "placeholder": "请填写服务范围",
        "required": true,
        "max_length": 2000
      }
    ]
  }
}
```

Card fields:

- `title`: required trimmed string, 1–160 characters.
- `description`: optional trimmed string, at most 2000 characters.
- `items`: required array, 1–20 items.

Item fields:

- `id`: optional trimmed stable identifier, 1–160 characters when present;
  non-empty IDs must be unique within the card.
- `question`: required trimmed customer-visible text, 1–500 characters and
  unique within the card.
- `description`: optional trimmed help text, at most 1000 characters.
- `placeholder`: trimmed text, default `请输入回答`, 1–200 characters.
- `required`: boolean, default `true`.
- `max_length`: integer, default `2000`, range 1–5000.

The component intentionally has no layout, input-mode, recommendation, or
default-answer fields. DClaw owns presentation. An Agent must not prefill a
customer fact. A question that can be represented as options belongs to a
selection component.

## Submit and trusted answer

The REST submit envelope is discriminated by the persisted component type.
A question form submits `answers` and must not submit `selected` or
`supplement`.

```json
{
  "version": 1,
  "answers": [
    {"id": "service_scope", "value": "主要维修空调和冰箱"}
  ],
  "idempotency_key": "client-stable-submit-key"
}
```

An item with an ID is referenced by ID. An item without an ID is referenced
by its exact question text. A reference must resolve to exactly one persisted
item. Duplicate, unknown, or missing references are rejected. The client may
not supply authoritative question labels.

Every persisted item appears once in the trusted answer, in card order:

```json
{
  "component_type": "question_form",
  "answers": [
    {
      "id": "service_scope",
      "question": "你目前主要提供哪些家电维修服务？",
      "value": "主要维修空调和冰箱"
    }
  ]
}
```

Leading and trailing whitespace is removed while internal newlines are
preserved. An unanswered optional item resolves to `null`. A missing or blank
required value returns `REQUIRED_ANSWER_MISSING`; an oversized value returns
`ANSWER_TOO_LONG`; an invalid, duplicate, or incomplete item reference returns
`INVALID_ANSWER_REFERENCE`.

The answer is persisted before the server returns its trusted `user_input`.
The client submits that value through the existing ordinary chat input path;
the interaction endpoint never invokes or waits for the Agent.

## Client behavior

The existing interaction shell, persistence recovery, input locking, and
ordinary chat submission path are reused.

- Each item is a full-width row with question, required/optional indication,
  help text, and an auto-growing textarea.
- Text wraps at arbitrary lengths. The textarea grows to a bounded height and
  then scrolls internally.
- Hover changes border/background only; focus uses the existing blue focus
  ring. No layout movement occurs.
- Missing required answers show an inline error and focus the first invalid
  field. Server failures preserve all entered text.
- Submitted cards render the persisted answers read-only.
- Mobile and dark-mode styling use the existing interaction-card tokens.
- The composer lock copy is generalized from “选择卡片” to “交互卡片”.

## LuYu behavior

LuYu must read the live catalog before creating any interaction. It must use
selection cards whenever a complete choice set can be formed, including the
desired-outcome and current-operation-status questions from the reported
conversation. Only genuinely open questions use `question_form`; multiple
open questions share one card with one item per question, up to the existing
three-question business limit.

Customer-facing prose must not duplicate card questions or ask the customer
to type option letters/numbers. A failed card creation is reported accurately
and is not silently downgraded to a text question.

## Compatibility and delivery

- The interaction capability group remains version `1`; this is an additive
  catalog component and optional answer branch.
- Existing selection-card JSON remains valid and unchanged.
- Styling changes do not affect Agent calls.
- Work is tested only in the local `basic-interactions` worktrees and local
  LuYu source. No push, package build, image build, or production deployment
  is part of this change.
