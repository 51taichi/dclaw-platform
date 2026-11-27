# DClaw Personal Credit Wallet and Unified AI Billing Design

## 1. Summary

DClaw will add a personal prepaid credit wallet so each customer can buy
credits through WeChat Pay or Alipay and spend those credits across text
conversations, AIGC Studio, and composite AI workflows.

The first release is intentionally personal-account only. The wallet ownership
model remains polymorphic so a later enterprise release can add organization
wallets, shared balances, member budgets, and enterprise price books without
replacing the core ledger or settlement engine.

This design establishes DClaw's own retail pricing authority. Supplier prices,
discounts, free quotas, and resource packs do not determine the customer-facing
price. Supplier billing evidence only determines whether a customer usage event
is eligible to settle.

## 2. Goals

- Let authenticated users buy credits without administrator intervention.
- Use one understandable credit balance across text, image, video, audio, and
  workflows.
- Give DClaw full control over retail prices and future price changes.
- Record every grant, purchase, hold, debit, release, refund, expiry, and
  administrator adjustment in an immutable, auditable ledger.
- Prevent duplicate payment credits and duplicate usage debits.
- Ensure an upstream request that produces no billable usage does not charge
  the customer.
- Preserve enough supplier usage detail for margin analysis and reconciliation.
- Keep the first release compatible with a future enterprise shared-wallet
  model.

## 3. Non-goals for the First Release

- Organizations, tenants, enterprise invitations, or enterprise member roles.
- Shared enterprise balances or per-member enterprise budgets.
- Customer-specific or enterprise-specific price books.
- Subscriptions and recurring monthly credit grants.
- User-to-user credit transfers, credit cash-out, or a credit marketplace.
- Automatic repricing based on supplier discounts or account-level promotions.
- Arbitrary recharge amounts.

## 4. Confirmed Commercial Rules

### 4.1 Credit value anchor

- 100 credits represent approximately CNY 1 of DClaw service value.
- 1,000 credits represent approximately CNY 10 of DClaw service value.
- This is a customer-facing value anchor, not a promise that supplier cost is
  equal to the credit value.
- DClaw targets approximately 50 percent aggregate gross margin initially, but
  administrators retain full authority to price any model or workflow above or
  below that target.

### 4.2 DClaw controls retail pricing

- DClaw publishes and owns every customer-facing rate.
- Competitor rates and supplier rates are internal reference data only.
- Supplier promotions, free quotas, volume discounts, resource packs, and
  negotiated procurement prices never change the price already shown to a
  customer.
- An administrator must explicitly publish a new DClaw price version to change
  customer pricing.
- A usage order locks its price version and price snapshot when it is created.
  Later price changes affect only new orders.

### 4.3 Settlement trigger

- If the supplier confirms billable usage, DClaw settles the usage order at the
  locked DClaw retail price.
- If the supplier confirms no billable usage, DClaw releases the hold and
  charges zero credits.
- If supplier billing status is unknown, the order remains in a reconciliation
  state until the platform can query the supplier or an administrator resolves
  it.
- A successful result is not itself the accounting source of truth, and a
  failed result does not automatically imply a refund. Supplier billability is
  the settlement trigger; DClaw's rate card determines the amount.

## 5. Credit Types and Expiry

The UI shows a combined available balance while the ledger preserves separate
credit lots.

| Credit type | Typical source | Expiry | Cash refundable |
| --- | --- | --- | --- |
| Purchased | WeChat Pay or Alipay recharge | Never | Unused principal only |
| Promotional | Signup or marketing grant | Configurable, normally 30-90 days | No |
| Package | Reserved for future subscriptions | Package period | No |

Consumption uses earliest-expiry-first allocation. If two lots expire at the
same time, promotional or package credits are consumed before permanent
purchased credits. Permanent purchased credits are consumed last.

Credits cannot be transferred, sold, cashed out, or moved to another user.

## 6. Signup Trial

- Grant 100 promotional credits after successful mobile-number verification.
- Trial credits expire seven days after grant.
- A risk identity may receive the grant only once. Risk identity can include
  verified mobile number, device signals, account links, and administrator
  review outcomes.
- Trial credits may be used for text and eligible standard image generation.
- Trial credits may not be used for video, high-cost models, or fixed-price
  premium workflows.
- Trial eligibility and capability restrictions are configuration, not
  hard-coded UI rules.

## 7. Recharge Products

The first release offers fixed recharge products.

| Payment | Permanent credits | 90-day promotional credits | Total |
| ---: | ---: | ---: | ---: |
| CNY 10 | 1,000 | 0 | 1,000 |
| CNY 50 | 5,000 | 300 | 5,300 |
| CNY 100 | 10,000 | 1,000 | 11,000 |
| CNY 500 | 50,000 | 7,500 | 57,500 |
| CNY 1,000 | 100,000 | 20,000 | 120,000 |

The checkout page must distinguish permanent purchased credits from expiring
promotional credits. Each payment order stores a complete product snapshot so
editing or disabling a product cannot alter an existing order.

Large custom purchases remain a manual sales process until enterprise billing
is designed.

## 8. Payment Channels and QR Codes

The first release supports:

- WeChat Pay Native payment.
- Alipay face-to-face precreate payment.

DClaw does not maintain a fixed collection QR image. For every recharge order,
the backend requests an order-specific payment URL from the selected channel.
The frontend renders that URL as a temporary QR code. Expired codes are
regenerated through a controlled retry or replacement flow.

Payment credentials are stored in the secret storage mounted at
`/app/working.secret`, not in ordinary application data or frontend bundles.
The administrator UI may update credentials, test a channel, and display
masked configuration status, but it must never return full secrets after save.

Payment completion is callback-driven with active order query as recovery.
Every callback is signature-verified, amount-verified, merchant-verified, and
idempotent. A successful payment order can grant credits exactly once.

## 9. Wallet and Ledger Model

### 9.1 Ownership

A wallet has an owner type and owner ID:

- First release: `owner_type=user`, `owner_id=users.id`.
- Future release: `owner_type=organization`,
  `owner_id=organizations.id`.

The first release creates one active credit wallet per user. Application code
must resolve a wallet through an ownership service rather than assuming a
wallet ID equals a user ID.

### 9.2 Ledger principles

- The ledger is append-only.
- Stored balances are projections derived from committed ledger entries and
  may be cached transactionally for performance.
- No application or administrator endpoint directly overwrites a balance.
- Every entry contains a business reference, idempotency key, operator or
  system actor, reason, timestamps, and relevant metadata.
- Monetary amounts use integer fen. Credit amounts use integer credits.
- A database transaction must atomically write ledger entries, lot allocations,
  and cached wallet totals.

### 9.3 Ledger event families

- `purchase_grant`
- `promotion_grant`
- `package_grant` reserved for future use
- `usage_hold`
- `usage_capture`
- `usage_release`
- `usage_adjustment`
- `credit_expiry`
- `payment_refund`
- `admin_grant`
- `admin_reversal`
- `chargeback_hold`
- `chargeback_capture`

Every debit retains the exact source-lot allocations so releases and refunds
can restore the correct credit types and expiry semantics.

## 10. Retail Price Catalog

### 10.1 Versioning

A published price catalog is immutable. Administrators create a draft, validate
it, and publish a new version with an effective time. Existing usage orders
retain their price snapshots.

Only one applicable published rule may win for a given model, capability, and
parameter set. Publication fails on ambiguous overlapping rules.

### 10.2 Supported units

- Text: credits per 1,000 input tokens and credits per 1,000 output tokens.
- Image: credits per generated image, with dimensions for generation versus
  editing, model, resolution, quality, and count.
- Video: credits per second or a fixed allowed-duration price, with dimensions
  for model, resolution, generation mode, audio, and quality.
- Audio: credits per character, second, minute, or request as supported by the
  provider.
- Fixed operation: credits per invocation for tools whose cost is not naturally
  token- or duration-based.
- Workflow: component sum by default, with an optional published fixed price.

The UI shows both a concrete model and a customer-friendly economic tier such
as Economy, Standard, or Advanced. The tier helps selection but never replaces
the exact price preview.

### 10.3 Initial guidance, not hard-coded prices

The following ranges guide the initial catalog and remain administrator-owned:

| Capability | Initial guidance |
| --- | ---: |
| Economy text input | 1 credit / 1K tokens |
| Economy text output | 2 credits / 1K tokens |
| Standard text input | 2 credits / 1K tokens |
| Standard text output | 5 credits / 1K tokens |
| Advanced text input | 8 credits / 1K tokens |
| Advanced text output | 25 credits / 1K tokens |
| Standard image | 50 credits / image |
| HD image or image edit | 80-150 credits / image |
| Standard 5-second video | 600-800 credits |
| Standard 10-second video | 1,200-1,600 credits |

These figures are seed configuration only. The product must not embed them in
business logic.

## 11. Usage Order Lifecycle

All billable operations create a durable usage order before contacting a
supplier.

Recommended states:

- `quoted`: retail price snapshot created.
- `held`: sufficient credits reserved.
- `submitted`: supplier request accepted or sent.
- `running`: asynchronous supplier work is active.
- `billable`: supplier evidence confirms billable usage.
- `not_billable`: supplier evidence confirms no billable usage.
- `captured`: DClaw credits permanently debited.
- `released`: held credits restored.
- `reconciling`: supplier billability is unknown.
- `cancelled`: cancelled before supplier billability.
- `reversed`: an administrator or correction flow reverses settlement.

State transitions use optimistic concurrency or row locks. Duplicate supplier
callbacks, client retries, worker retries, and process restarts cannot capture
or release a usage order twice.

## 12. Text Conversation Billing

Text charges use actual recorded input and output tokens and the usage order's
locked rate snapshot.

DClaw already records user ID, model name, input tokens, and output tokens. The
new settlement integration must preserve provider ID and a stable model price
key so two providers exposing similarly named models cannot collide.

For ordinary requests, the platform obtains a conservative hold before model
execution and captures the actual calculated retail amount after supplier usage
is available. Unused held credits are released. If a multi-step agent performs
several model calls, each supplier call produces a child usage item under the
customer task.

Before every additional model or paid-tool step, the agent checks the remaining
wallet balance and task budget. A task cannot create a negative wallet balance.
When the next step cannot be funded, execution pauses with a resumable
balance-insufficient state.

The customer can set a task-level spending cap. The initial default is 300
credits, configurable by the platform and overridable within platform limits.

The conversation UI displays per-response usage, including model, input tokens,
output tokens, charged credits, and resulting available balance.

## 13. AIGC Studio Billing

Before submission, AIGC Studio displays the exact DClaw quote derived from the
selected model and parameters. Examples of billable dimensions include:

- text-to-image, image-to-image, and image editing;
- text-to-video and image-to-video;
- resolution and quality;
- video duration;
- audio inclusion;
- output count;
- model-specific premium modes.

The full quoted amount is held before submission. Supplier task IDs and status
evidence are stored on the usage order. On billable confirmation, DClaw captures
the locked retail price. On confirmed non-billable status, DClaw releases the
hold. Unknown outcomes enter reconciliation rather than being charged or
released speculatively.

Automatic retries belong to the same logical usage order unless the supplier
creates separately billable attempts. A client-initiated regenerate action is
a new usage order.

## 14. Workflow Billing

The default workflow price is the sum of its billable component usage items.
The customer sees a running total and, when feasible, an estimate before start.

Administrators may publish a fixed retail price for a named workflow. A
fixed-price workflow:

- holds its full fixed price before execution;
- keeps internal component usage and supplier billability for cost and margin
  reporting;
- charges the customer according to the workflow price and its published
  settlement/refund policy, not the component retail sum;
- stores a workflow price snapshot on the parent usage order;
- does not expose supplier procurement discounts to the customer.

Each fixed-price workflow must define cancellation and partial-failure policy
before publication. Ambiguous workflow refund policies cannot be published.

## 15. Supplier Billing Evidence and Reconciliation

Supplier adapters normalize evidence into:

- supplier request or task ID;
- provider and model price key;
- billability status;
- input/output tokens or other usage quantities;
- supplier-reported status and error code;
- raw evidence reference with sensitive fields removed;
- first and last checked times.

When a supplier returns usage but not money, the usage still establishes
billability. DClaw retail settlement uses the locked DClaw price rule. Supplier
cost may be calculated separately from an internal cost catalog for margin
reporting.

A reconciliation worker queries unknown asynchronous tasks with bounded retry
and backoff. Old unresolved tasks appear in an administrator queue. Manual
resolution requires a reason and produces an audit record.

Monthly supplier invoices can be compared with normalized supplier usage for
finance analysis. Invoice discounts never retroactively alter customer debits.

## 16. Refund Rules

### 16.1 Recharge payment refund

- Within seven days, a completely unused recharge may be refunded in full to
  the original payment route. All credits and promotional grants from that
  order are removed.
- After usage, the customer may request a refund of unused purchased principal.
- Remaining promotional credits from the order are removed first.
- Promotional credits already consumed reduce the refundable value before
  calculating the remaining purchased principal.
- Used purchased credits are not refundable.
- Purchased credits refund at 100 credits per CNY 1.
- Promotional, package, expired, and trial credits have no cash value.
- Refunds return only to the original payment route.
- Refund processing freezes the affected credit amount.
- An invoiced order requires the appropriate invoice reversal workflow.

Final customer terms require legal review for the operator's jurisdiction,
business entity, and exact service classification.

### 16.2 Usage correction

Incorrect DClaw debits are reversed as credits through compensating ledger
entries. The original ledger entries remain visible. Cash refunds are a
separate payment workflow and are not simulated by editing wallet balances.

## 17. Customer Experience

### 17.1 Wallet page

- Available, held, and total balances.
- Breakdown by purchased, promotional, and future package credits.
- Upcoming expiries.
- Recharge products and payment channel selection.
- Recharge orders and refund status.
- Credit ledger with filters for recharge, consumption, refund, grant, and
  expiry.

### 17.2 Price transparency

- Model tier and exact model name.
- Exact or estimated credits before execution.
- Parameters that change price.
- Per-response or per-generation final charge.
- Clear indication when credits are held or under reconciliation.
- Balance-insufficient actions link directly to recharge.

### 17.3 Payment page

- Order-specific dynamic QR code.
- Amount, permanent credits, promotional credits, and expiry.
- QR expiry countdown and safe regeneration.
- Polling-backed status recovery in addition to verified callbacks.
- No client-supplied authority over paid amount or granted credits.

## 18. Administrator Experience

- Recharge product drafts, activation, deactivation, ordering, and snapshots.
- WeChat Pay and Alipay secret configuration with masked display and connection
  tests.
- Price catalog drafting, validation, comparison, scheduled publication, and
  rollback by publishing a new version.
- Model-to-price-key mapping and supplier evidence adapter status.
- Wallet lookup and immutable ledger inspection.
- Controlled grants and reversals requiring reason codes.
- Recharge order, refund, usage order, and reconciliation queues.
- Revenue, credits sold, credits consumed, supplier cost estimate, gross margin,
  outstanding purchased-credit liability, expiring promotions, and failed-task
  reports.
- Exportable finance and audit records.

Platform administrators do not receive implicit authority to silently rewrite
balances or ledger history.

## 19. Security and Abuse Controls

- Verify all payment signatures and supplier callbacks.
- Verify merchant identity, application identity, currency, amount, order ID,
  and payment status server-side.
- Store secrets only in secret storage and never log them.
- Use idempotency keys for payment creation, payment callback, credit grant,
  usage hold, capture, release, and refund.
- Rate-limit checkout creation, callback endpoints, signup grants, and refund
  requests.
- Prevent client-controlled prices, wallet IDs, credit amounts, and owner IDs.
- Record actor, IP context where appropriate, request correlation ID, and reason
  for sensitive administrator actions.
- Freeze or review wallets associated with chargebacks, automated signup abuse,
  suspicious recharge/refund loops, or credential compromise.
- Never allow the available balance to become negative.

## 20. Data Consistency and Failure Handling

- PostgreSQL is the accounting source of truth. Redis may cache read models or
  coordinate workers but cannot be the only copy of wallet state.
- Ledger and cached balance changes occur in one PostgreSQL transaction.
- External calls never occur inside a long-held database transaction.
- Use an outbox or equivalent durable dispatch mechanism between accounting
  commits and asynchronous processing.
- Payment and supplier callbacks are durable before business processing.
- Worker retries are idempotent.
- A repair command can rebuild wallet projections from ledger entries and
  report discrepancies without deleting history.
- Backups and restore procedures must include wallet, payment, price catalog,
  usage order, refund, and audit tables as one consistent database set.

## 21. Migration and Rollout

### Phase 1A: accounting foundation

- Add wallets, credit lots, ledger, price catalog, usage orders, and audit
  foundations.
- Create a personal wallet for every existing user.
- Grant no retroactive paid balance by default.
- Keep billing enforcement disabled while recording shadow quotes and usage.

### Phase 1B: shadow billing

- Calculate customer credits without debiting wallets.
- Compare model mappings, token usage, AIGC tasks, supplier evidence, and cost
  reports.
- Resolve missing usage instrumentation before enabling real settlement.

### Phase 1C: administrator-funded pilot

- Allow administrator grants to selected pilot accounts.
- Enable real debit enforcement for pilot users.
- Validate holds, captures, releases, reconciliation, and support procedures.

### Phase 1D: customer recharge

- Enable WeChat Pay and Alipay sandbox tests, then production channels.
- Publish recharge products, refund terms, and customer wallet pages.
- Enable billing for new customers first, then migrate existing customers using
  an announced policy.

### Phase 2: enterprise wallets

- Add organizations and organization membership.
- Add organization-owned wallets and member budgets.
- Add enterprise roles, shared balance reporting, and enterprise price books.
- Migrate wallet resolution through the existing owner-type abstraction rather
  than replacing personal ledger records.

## 22. Testing and Acceptance Criteria

### Accounting invariants

- A wallet's projected totals exactly match its ledger and active lots.
- Available plus held credits equals the unexpired unconsumed lot total.
- No wallet can become negative.
- A business idempotency key cannot produce two financial effects.
- Every capture consumes known held allocations or an explicitly authorized
  settlement path.
- Every reversal references the original entry.

### Payment acceptance

- Duplicate and reordered callbacks grant credits once.
- Wrong amount, merchant, signature, currency, or order status grants nothing.
- Callback loss recovers through active query without duplicate grant.
- QR regeneration cannot create two payable orders that both credit one
  business purchase without explicit handling.
- Refunds cannot exceed refundable principal and cannot execute twice.

### Usage acceptance

- Confirmed supplier billability captures the locked DClaw retail price.
- Confirmed non-billability releases all held credits.
- Unknown status does not silently capture or release.
- Supplier discounts do not change customer debit.
- Published price changes do not alter existing usage orders.
- Text calls record correct provider, model, input tokens, output tokens, and
  customer debit.
- AIGC retries and callbacks do not duplicate debit.
- Fixed-price workflows preserve component cost evidence while charging the
  fixed customer price exactly once.

### Customer acceptance

- A customer can understand the quote before an expensive operation.
- Wallet balance, holds, consumption, expiry, and refunds are traceable.
- Recharge checkout clearly separates permanent and promotional credits.
- Insufficient balance prevents new paid work without losing completed output.

## 23. Observability

Monitor and alert on:

- payment callback verification failures;
- successful payments without credit grants;
- usage orders stuck in held or reconciling state;
- negative-balance invariant attempts;
- ledger/projection mismatches;
- supplier billable usage without a customer usage order;
- unexpected zero-usage rates by provider and model;
- refund and chargeback anomalies;
- price rule misses and ambiguous rule matches;
- margin deterioration by model and workflow.

## 24. Decisions Deferred to Implementation Planning

The implementation plan will select concrete table and API names, migration
mechanics, provider adapter boundaries, frontend routes, and rollout feature
flags. Those choices must preserve the commercial rules and accounting
invariants in this design.

