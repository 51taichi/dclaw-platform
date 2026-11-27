# Unified Model Billing Context Design

Date: 2026-08-30
Status: Approved for planning

## Purpose

DClaw must enforce credit billing for every user-triggered model call, not only
OpenAPI traffic. A zero-credit user must not be able to bypass billing by using
the web console, an expert team, an automation, a scheduled task, or an external
channel. Every charge must be explainable to the customer through durable usage
and ledger records.

This design extends the existing OpenAPI wallet, usage-order, usage-item,
pricing, hold, settlement, reconciliation, and reporting contracts into one
entry-point-independent billing system.

## Scope

The change covers model calls initiated through:

- client and mobile expert conversations;
- expert-team runs;
- OpenAPI expert and expert-team publications;
- automations and scheduled tasks;
- external channels such as WeChat and DingTalk;
- future user-facing entry points that use the shared model factory.

Non-model operations such as browsing history, managing files, editing experts,
or reading knowledge do not consume credits.

## Product Decisions

- Production runs in `enforced` mode immediately. There is no free allowance or
  observation period for existing users.
- Insufficient balance terminates the next model call before supplier contact.
- Expert teams retain completed steps and pause before the first unaffordable
  step. After funding the wallet, the customer can type “continue” or use a
  “continue after top-up” action.
- Confirmed supplier usage is charged. A failure before supplier contact is not
  charged. Uncertain post-contact outcomes retain their hold for reconciliation.
- System work is free only when it carries an explicit audited exemption.
  Missing billing ownership is an error, never an implicit exemption.

## Architecture

### General billing execution context

Introduce a general `BillingExecutionContext` carried through a `ContextVar`.
It contains:

- payer user identity and wallet identity;
- source kind: `client`, `openapi`, `expert_team`, `automation`, `schedule`, or
  `channel`;
- source identifiers for the business task, expert, expert-team run,
  automation, schedule, or channel binding;
- a unique execution identity and idempotency namespace;
- the locked price-catalog version;
- enforced billing mode;
- an optional explicit system-exemption marker and audit reason.

Every entry point creates the context before user code or model execution and
resets it with the original ContextVar token in `finally`. Child async tasks
inherit the intended context, while unrelated requests cannot share it.

OpenAPI's existing execution fence, durable invocation ownership, and replay
contract remain authoritative. The general context wraps or composes with the
OpenAPI execution context rather than creating a second charge.

### Responsibilities

Entry points are responsible for:

- authenticating the caller;
- resolving the payer and source metadata;
- creating or resuming the durable usage order;
- installing and cleaning up the billing context;
- translating billing failures into channel-appropriate responses.

The shared model meter is responsible for:

- rejecting user model calls without a valid context;
- obtaining the authoritative locked price rule;
- reserving a conservative upper bound before supplier contact;
- recording durable supplier-contact state;
- settling from verified usage evidence;
- releasing holds for known non-billable outcomes;
- retaining holds for unknown outcomes;
- projecting item, order, wallet, and invocation totals atomically.

The analytics token queue remains secondary. Durable financial writes complete
before analytics enqueueing, and an analytics failure cannot reverse or hide a
charge.

## Payer Resolution

- Client, mobile, expert, expert-team, and OpenAPI calls charge the initiating
  authenticated user.
- Automations and scheduled tasks charge their durable owner.
- External channels charge the user bound to the channel identity.
- A missing, deleted, disabled, or ambiguous payer fails closed before model
  contact.
- Maintenance and health-check work is exempt only through an explicit audited
  system context. Ordinary admin activity is not automatically free.

## Durable Accounting Model

Each user-visible business request owns one usage order. Every actual model call
owns one usage item. Expert-team members share the team's order but receive
separate items for each call.

Stable item keys derive from the execution identity and call identity, not a
process-local counter. They must remain unique across processes, restarts,
retries, stream reconnects, and OpenAPI replays.

Each item records the safe reporting dimensions needed by customers:

- call sequence;
- source kind;
- expert or expert-team role;
- model, provider, and capability;
- input and output tokens;
- held, charged, and released credits;
- billability and execution outcome;
- price-catalog version;
- creation and settlement timestamps.

Supplier references, raw evidence, API-key identifiers, internal idempotency
keys, allocation identifiers, database identifiers, prompts, skills, source
files, and sealed-agent assets are never returned by customer serializers.

## Model Call State Machine

For every model call:

1. Validate the execution context and payer.
2. Lock the authoritative catalog and price rule.
3. Calculate a conservative maximum charge from input and provider output caps.
4. Atomically reserve that amount from eligible credit lots.
5. If reservation fails, persist the controlled insufficient-balance outcome and
   stop before supplier contact.
6. Persist the supplier-contact marker before invoking the provider.
7. On verified official usage, capture the actual charge and release excess
   hold in one transaction.
8. On an explicit pre-contact or known no-charge rejection, release the entire
   hold.
9. On timeout, disconnect, cancellation, storage uncertainty, or missing
   verified evidence after contact, retain the hold and mark the item and order
   `reconciling`.
10. Update durable aggregates before emitting terminal UI or channel events.

Retries and replays with matching evidence return the durable outcome. Drift in
payload, usage, evidence, or source identity fails with a controlled conflict
and never creates a second charge.

## Expert-Team Pause and Resume

Before each team member's model call, the meter reserves only that call's
conservative bound. The system does not freeze a speculative maximum for the
entire team.

When the next reservation is unaffordable:

- no later supplier is contacted;
- completed member results and charges remain intact;
- the current run becomes `paused_insufficient_balance`;
- the next unexecuted member and required estimated credits are persisted;
- the client shows completed steps, charged credits, available credits, and the
  top-up/continue actions.

After a top-up, either an explicit UI action or the user's “continue” intent
resumes the same run. Only a run whose durable state is paused for insufficient
balance can consume that intent. Resume starts from the first uncompleted member
and rechecks the wallet. Stable step/item keys prevent duplicate execution and
charging under repeated clicks, messages, reconnects, or restarts.

Ordinary single-call experts, channels, automations, and schedules fail their
current attempt on insufficient balance. The user or scheduler may start a new
attempt after funding; they do not reuse expert-team continuation semantics.

## Customer Experience and Reporting

The wallet UI exposes:

- available, held, purchased, promotional, and package balances;
- usage-order history;
- per-model-call usage details;
- wallet ledger entries;
- reconciliation status;
- daily and monthly summaries;
- expert-team pause and continuation state.

Usage orders can be filtered by date, source, expert, expert team, model,
provider, and status. An order shows source, expert/team, status, call count,
token totals, reserved credits, charged credits, released credits, and remaining
balance. An item shows call sequence, expert role, model, provider, capability,
input/output tokens, charged credits, status, and catalog version.

All entry points use a consistent insufficient-balance error containing safe
fields for available credits, estimated required credits, and a top-up action.
The web UI must display it explicitly rather than leaving an empty response.
Expert-team runs instead display a paused terminal event with continuation
controls.

Administrators retain the existing extended audit and reconciliation views.
Customers see only allowlisted public fields.

## Compatibility and Rollout

- Deployment activates `enforced` for every covered user entry point.
- Existing zero-balance users are blocked from new model calls until funded.
- Existing OpenAPI idempotency, fencing, recovery, price snapshots, and
  reconciliation semantics must not regress.
- In-flight work present during deployment converges through durable item/order
  state and cannot be charged twice after restart.
- Historical unbilled records remain historical and are not retroactively
  charged.
- A missing catalog, rule, wallet, payer, or context fails closed.

## Error Handling

- Insufficient balance: controlled business error or expert-team pause; no
  supplier contact.
- Invalid/missing price rule: service unavailable billing error; no supplier
  contact.
- Explicit provider no-charge rejection: release hold and record the failure.
- Verified provider use: charge actual usage even when the business response
  later fails.
- Unknown post-contact outcome: retain hold and expose reconciliation status.
- Financial persistence failure: do not report a free success; preserve a
  durable contact/reconciliation marker or fail before contact.
- Frontend, channel, and automation adapters must surface the durable outcome;
  they may not swallow billing errors.

## Verification

Acceptance requires tests for:

- client/mobile experts, expert teams, OpenAPI, automations, schedules, and
  external channels;
- valid balance, zero balance, exact-boundary balance, and concurrent spending;
- expert-team partial completion and both continuation mechanisms;
- successful streams, unstarted/partial stream close, disconnect, timeout,
  cancellation, and provider failure;
- replay, retry, restart, and multi-worker idempotency;
- verified, non-billable, and unknown settlement outcomes;
- consistency across wallet balances, lots, ledger entries, usage items, usage
  orders, and customer summaries;
- customer-field redaction and administrator audit visibility;
- SQLite behavior, real PostgreSQL locking/concurrency, schema upgrades, startup
  recovery, and deployment rollback.

The implementation is complete only when every covered user entry point either
installs a valid billing context or fails closed before model contact.
