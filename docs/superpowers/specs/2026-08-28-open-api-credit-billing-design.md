# OpenAPI Credit Billing Integration Design

**Status:** Approved design
**Date:** 2026-08-28
**Depends on:** `2026-08-25-credit-wallet-billing-design.md`
**Scope:** Connect existing OpenAPI identity and token-usage flows to the
personal credit wallet and immutable billing ledger.

## 1. Purpose

DClaw already binds each OpenAPI publication to a durable runtime user through
`bound_user_id`. OpenAPI authentication puts that user into request and agent
runtime context, and the existing token-usage subsystem records model usage by
that user. The missing piece is an auditable, request-level bridge from an
OpenAPI invocation and its individual model calls to the credit wallet.

This integration must:

- attribute charges to the publication's bound runtime user;
- reserve credits before incurring supplier cost;
- charge only when supplier evidence says DClaw was charged;
- support one invocation containing multiple agent or expert-team model calls;
- expose customer-visible credit details without exposing supplier commercial
  data or prompt content;
- deploy in shadow and observation stages before enforcement;
- never retroactively charge historical token-usage records.

WorkBuddy is a product-experience reference only. DClaw owns its retail price
catalog and all customer prices. The adopted experience principles are a
unified credit balance, visible usage history, low-balance warnings, top-up
entry points, and deterministic termination when an unattended OpenAPI request
runs out of credits.

## 2. Non-goals

This design does not:

- introduce organizations or an enterprise shared wallet;
- use supplier cost or discounts to calculate customer retail prices;
- back-charge token usage recorded before the billing cutover;
- store prompts, generated content, API key plaintext, or supplier secrets in
  accounting tables;
- make the asynchronous token statistics queue a financial source of truth;
- allow overdrafts or invoke a supplier after available credit is exhausted.

## 3. Ownership and Attribution

Every OpenAPI charge belongs to the personal wallet of
`open_api_publications.bound_user_id`.

The following fields are attribution and audit dimensions, not wallet-owner
selectors:

- API key creator;
- external application owner;
- `external_user_id` supplied by the caller;
- API key identifier;
- publication owner.

The authoritative chain is:

```text
API key -> publication -> bound_user_id -> personal wallet
```

The authenticated OpenAPI request must resolve this chain server-side. A
client may not provide `wallet_id`, owner identity, price, or credits.

Future enterprise wallet routing may replace the personal wallet through a
trusted server-side funding policy. It does not alter the first-release owner
rule.

## 4. Request and Billing Identity

Each accepted OpenAPI request receives a server-generated `invocation_id` and
exactly one billing usage order. Both records store a durable bidirectional
link:

```text
open_api_invocations.billing_usage_order_id -> billing_usage_orders.id
billing_usage_orders.source_type = "open_api"
billing_usage_orders.source_id = invocation_id
```

One invocation can contain multiple model-call usage items. This covers normal
agents, expert teams, tools that invoke models, retries inside a workflow, and
multi-stage generation.

### 4.1 Client idempotency

OpenAPI accepts an optional `Idempotency-Key` header. Its internal namespace is
the tuple `(app_id, publication_id, idempotency_key)`.

- Same key and canonical request payload returns the existing invocation and
  does not call the supplier or charge again.
- Same key with a different canonical payload returns HTTP 409 with code
  `idempotency_conflict`.
- A missing key means each request is a distinct invocation.
- Model-call usage items use stable internal item keys derived from the
  invocation and call sequence or supplier request identity.

## 5. Runtime Billing Context

After OpenAPI authentication and before agent execution, DClaw creates or
recovers the invocation and usage order, resolves the wallet, locks the active
retail catalog, and installs an immutable billing context containing:

```text
invocation_id
usage_order_id
wallet_id
bound_user_id
app_id
api_key_id
publication_id
catalog_version
```

Agent runners, expert-team orchestration, tool-driven model calls, and nested
model calls must inherit this context. Context propagation must remain correct
across async tasks and streaming generators and must not leak between
concurrent requests.

## 6. Reservation and Budget Rules

OpenAPI is unattended, so DClaw cannot pause to ask a user whether to continue.
It uses incremental conservative reservations with a hard no-overdraft rule.

### 6.1 Initial reservation

Before the first supplier call, DClaw estimates the first model call using:

- the actual known input tokens or a conservative tokenizer estimate;
- the caller's requested maximum output tokens, capped by platform policy; or
- the platform-configured default output reserve when no maximum is supplied;
- the locked DClaw retail price catalog.

If the wallet cannot fund the reservation, DClaw returns
`insufficient_credits` and does not call the supplier.

### 6.2 Incremental reservation

Before every subsequent model call, including expert-team steps, DClaw checks
whether the existing hold covers that call's conservative estimate. If not, it
attempts an incremental hold from the same wallet.

- If funded, execution continues.
- If unfunded, DClaw immediately stops before the next supplier call.
- Completed supplier calls retain their results and are settled normally.
- Unused holds are released.
- The public result is `partially_completed` with code
  `insufficient_credits` when prior steps completed.

“Incremental hold” is an internal accounting mechanism, not customer-facing
terminology. Customers see task budget, credits used, remaining balance,
warnings, and top-up actions.

### 6.3 Invocation budget

Every invocation has a server-controlled maximum credit budget. A publication
may set a lower maximum through trusted admin configuration. The client cannot
raise the platform maximum. Reaching the budget terminates the request before
another supplier call.

## 7. Supplier Evidence and Settlement

The rule is: DClaw charges the customer only when upstream charged DClaw.
Failure alone is not proof of non-billability.

Each model-call usage item independently records one of:

- `billable`: a normal supplier response contains official usage evidence or
  another approved supplier-specific billing confirmation;
- `not_billable`: the request did not reach the supplier, the supplier
  explicitly reports no charge, or a provider-specific adapter proves the task
  was never created;
- `unknown`: the supplier may have created or executed work but DClaw cannot
  prove whether it charged, including ambiguous timeout, disconnect, or 5xx
  outcomes.

Rules:

- `billable` captures the DClaw retail price for actual measured usage.
- `not_billable` releases the corresponding reservation.
- `unknown` retains only the corresponding reservation and enters
  reconciliation.
- Supplier evidence stores a validated, minimized JSON record, supplier
  reference, evidence timestamp, and adapter version.
- Manual resolution requires an authenticated actor, reason, timestamp, and
  immutable audit record.

An invocation may contain a mixture of all three states. Confirmed items settle
independently while unknown items remain reconciling. The order is complete
only when every item is resolved.

## 8. Pricing

DClaw's published retail catalog is the only customer price authority.

- The invocation locks a catalog version before its first supplier call.
- Every usage item stores provider, model, capability, parameters, input and
  output tokens, matched rule, unit breakdown, and immutable retail-price
  snapshot.
- Each input/output or quantity component is rounded up according to the
  existing pricing engine.
- Supplier cost, discounts, promotions, rebates, or activity pricing never
  select a rule or alter the customer price.
- Final capture uses actual measured usage, not the conservative reservation.
- Excess reservation is released to its original lots; expired remainder
  follows the existing expiry rules.

## 9. Financial and Statistical Recording

Billing usage items are written synchronously and durably because they are the
financial source of truth. The existing token-usage queue remains asynchronous
and supports analytics only.

For each model call:

1. reserve before supplier execution;
2. obtain a supplier outcome and usage evidence;
3. synchronously append or idempotently recover the usage item;
4. settle or mark it reconciling in the same controlled workflow;
5. asynchronously emit the existing token-statistics event.

If financial recording fails after an ambiguous supplier outcome, the order
must become `reconciling`; the system must not assume no charge. A token
statistics queue failure cannot change financial settlement.

`open_api_invocations.token_summary` is updated from durable billing items and
contains aggregate model and token totals for the OpenAPI management console.

## 10. Data Model Changes

### 10.1 `open_api_invocations`

Add or expose:

- `billing_usage_order_id`;
- `billing_status`;
- `quoted_credits`;
- `captured_credits`;
- `released_credits`;
- `billing_error_code`;
- durable aggregate `token_summary`.

### 10.2 `billing_usage_orders`

Use or add:

- `source_type` and `source_id`;
- invocation budget and current reservation;
- locked catalog version and price snapshot;
- aggregate held, captured, released, and reconciling credits;
- final or partial-completion status.

### 10.3 `billing_usage_items`

Each model call records:

- stable `item_key`;
- provider, model, and capability;
- pricing parameters;
- input and output tokens or other measured quantity;
- quoted and actual credits;
- billability state;
- supplier reference and minimized evidence;
- matched rule and immutable price snapshot;
- start and finish timestamps.

Database migration must be idempotent for both fresh and existing PostgreSQL
installations. SQLite remains supported in repository tests.

## 11. API Contracts

Customer billing APIs include:

```text
GET /api/user/billing/wallet
GET /api/user/billing/ledger
GET /api/user/billing/usage-orders
GET /api/user/billing/usage-orders/{order_id}
GET /api/user/billing/open-api-summary
```

User queries are always restricted to the authenticated user's wallet. Admin
queries may filter by user, publication, application, API key, provider, model,
date, and billing status.

OpenAPI responses expose identifiers and billing state without supplier
commercial data. Initial response headers may include:

```text
X-DClaw-Invocation-Id
X-DClaw-Billing-Status
```

Because a streaming response does not know final usage at header time, final
credits are delivered through a terminal SSE event:

```json
{
  "type": "billing.completed",
  "invocation_id": "...",
  "credits_used": 18,
  "credits_remaining": 982,
  "billing_status": "captured"
}
```

An insufficient-balance termination uses:

```json
{
  "type": "billing.interrupted",
  "code": "insufficient_credits",
  "status": "partially_completed",
  "completed_steps": 3,
  "remaining_credits": 12,
  "required_credits_for_next_step": 25,
  "invocation_id": "..."
}
```

If the first reservation fails, the request returns the existing controlled
insufficient-credit HTTP error before streaming begins.

## 12. Customer and Admin Experience

The customer credit center shows:

- available, held, purchased, promotional, and package credits;
- daily and monthly consumption;
- OpenAPI, chat, and AIGC consumption categories;
- filters for time, model, publication, application, and status;
- one expandable order per OpenAPI invocation;
- model-call token details and DClaw price version;
- captured, released, reconciling, and insufficient-credit states;
- low-balance warnings and a top-up entry point.

It never exposes supplier cost, internal discounts, raw evidence payloads,
prompts, generated content, or secret credentials.

The admin console adds platform summaries, user/application/publication/API-key
rankings, reconciliation queues, price-version traceability, and shadow-versus
token-statistics comparison reports.

## 13. Rollout Modes

### 13.1 Shadow

- Create invocation links, usage orders, usage items, evidence, and retail
  quotes.
- Do not hold or mutate wallet balances.
- Compare durable billing items with existing token statistics.

### 13.2 Observe

- Calculate reservations and record whether each request would pass.
- Do not hold or mutate balances.
- Measure how often customers would be interrupted and whether initial credit
  grants and price rules are reasonable.

### 13.3 Enforced

- Perform real reservations and evidence-gated settlement.
- Stop before the next supplier call when credits are insufficient.
- Retain unknown reservations for reconciliation.

The default remains `shadow`. Promotion to `enforced` requires explicit admin
action after acceptance gates pass.

## 14. Cutover and Historical Data

The system stores `billing_cutover_at` when enforcement starts.

- Token usage before cutover remains visible as historical statistics.
- Historical rows are never converted into debit ledger entries.
- Only calls with a durable invocation, usage order, usage items, evidence,
  and locked price snapshot can create customer charges.
- Reports clearly label the historical-statistics and financial-ledger eras.

## 15. Failure and Recovery Rules

- Missing catalog: return `503 catalog_not_ready`, no supplier call.
- Insufficient initial balance: return controlled insufficient-credit error,
  no supplier call.
- Insufficient incremental balance: stop before the next supplier call and
  return a partial-completion terminal event.
- Client SSE disconnect: background execution performs evidence collection and
  accounting finalization.
- Process restart: recover incomplete invocation/order pairs by durable status
  and idempotency keys.
- Ambiguous supplier result: retain the relevant hold and reconcile.
- Financial write failure after supplier contact: mark reconciling; never infer
  `not_billable`.
- Duplicate financial event: return the existing item/settlement result.
- Reconciliation timeout: surface to the admin queue; do not guess.

## 16. Acceptance Criteria

1. An API key bound to user 24 can debit only user 24's configured wallet.
2. A replay with the same idempotency key and payload does not invoke or charge
   twice.
3. A conflicting replay returns `409 idempotency_conflict`.
4. A three-call expert team produces one order and three usage items.
5. Supplier-billable items capture actual retail credits.
6. Supplier-not-billable items release their reservations.
7. Mixed billability partially settles and retains only unknown reservations.
8. Insufficient balance stops before the next supplier call.
9. Completed steps and their legitimate charges survive partial termination.
10. SSE disconnect does not prevent financial finalization.
11. A token-statistics queue failure does not lose or duplicate billing items.
12. Shadow and observe modes never mutate wallet balances.
13. Regular users cannot query another user's orders or ledger.
14. Historical token data is not back-charged.
15. PostgreSQL concurrency cannot create a negative balance or duplicate
    settlement.
16. Restart recovery converges incomplete orders to a durable terminal or
    reconciling state.
17. Token and credit details are visible to the bound customer without prompt,
    secret, or supplier-cost disclosure.

## 17. Enforcement Readiness Gate

Enforcement may be enabled only after:

- shadow coverage includes normal agent, expert-team, multi-model, timeout,
  disconnect, retry, and process-restart scenarios;
- durable billing item totals match expected model usage within documented
  adapter tolerances;
- duplicate-charge tests pass;
- live PostgreSQL locking, migration, and recovery tests pass;
- reconciliation operations and customer low-balance guidance are available;
- an administrator explicitly records `billing_cutover_at` and enables
  enforced mode.
