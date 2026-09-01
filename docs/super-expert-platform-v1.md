# Super Expert Platform v1

This API is the generic platform capability layer used by officially signed super experts. It exposes platform primitives; it does not contain an Agent's business stages, Controller, Harness, Skills, scoring, or content methods.

## Capability groups

- Card: `card.create`, `card.update`.
- Human-guided AIGC: `aigc.task.create`, `aigc.task.resume`, `aigc.task.cancel`, `aigc.guide.update`, `aigc.asset.submit`, `aigc.review.complete`.
- Runtime orchestration and host capabilities are documented in [Workspace Turn Orchestration v1](workspace-turn-orchestration-v1.md).

Every command uses contract version `1`, an installation-bound grant, an idempotency key, a unique event ID, and the exact binding:

`installation_id + conversation_id + agent_task_id + content_revision + material_task_id + canvas_id + node_id`.

Assets are additionally bound by `asset_id`. A tenant, conversation, task, revision, canvas, node, material, or asset mismatch is rejected.

## Task lifecycle

`WAITING_TO_START → IN_PROGRESS → SUBMITTED → REVIEWING → ACCEPTED`

Review can instead produce `REVISION_REQUIRED`, followed by `IN_PROGRESS → SUBMITTED → REVIEWING`. Resuming a revision opens a new asset slot while immutable events retain the previously reviewed asset. `CANCELLED` and `INVALIDATED` are terminal. Refreshing or navigating away does not cancel the durable task; the guide resumes from the stored task, operation, canvas, node, and local step state.

Commands emit one idempotent standard event: `card.created`, `card.updated`, `aigc.task.created`, `aigc.task.resumed`, `aigc.task.cancelled`, `aigc.guide.updated`, `aigc.asset.submitted`, or `aigc.review.completed`. Duplicate identical commands replay their original result without duplicate runtime events. Reusing an event ID or idempotency key for different content fails.

## Card and guide behavior

Chat renders platform runtime events as task cards. Repeated clicks are idempotent. The deep link carries only trusted task identity; the AIGC page reloads the authoritative task and operation contract from DClaw.

The right-side guide uses stable control IDs from `src/qwenpaw/aigc/contracts/aigc-operation-contract-v1.json`. Each step declares its instruction, success signal, and recovery action. A missing control or incompatible contract blocks progress; neither the UI nor a model guesses a replacement. The generated novice manual is [AIGC Operation Manual v1](generated/aigc-operation-manual-v1.md).

## Security and failure rules

Only the exact capabilities declared by the current signed package and granted as a whole may be called. Ordinary Agents cannot self-upgrade by prompt or manifest text. Platform errors, timeouts, stale revisions, deleted bindings, missing controls, wrong assets, or unauthorized calls make no Agent business progress.

An accepted material is only a usable material. It cannot itself mark a complete content item as reviewed, publishable, or published. The Agent's own Controller and review Gate remain authoritative.

## v2 extension point

Version 1 is `HUMAN_GUIDED`: the customer performs stable operations with step-by-step assistance. Operation objects already use executor-independent `operation_id`, arguments, preconditions, expected result, idempotency, and version fields. A future v2 may add `AI_EXECUTED` or `HYBRID` executors without changing the Agent's business task semantics. v1 does not expose automatic publishing or arbitrary browser control.

