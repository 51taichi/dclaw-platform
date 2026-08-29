# DClaw Manual Top-up Wallet UI — Phase 1 Design

## 1. Purpose

This phase makes the existing personal credit wallet usable by customers and
operators without introducing an automatic payment gateway. Customers can see
their balance and OpenAPI consumption, scan the platform's existing collection
QR code, submit a top-up claim, and follow its review status. An authenticated
administrator can approve or reject the claim. Approval appends an auditable,
idempotent purchased-credit grant through the existing ledger; no endpoint
edits a wallet balance directly.

This design spans two repositories:

- `dclaw-server` owns products, top-up claims, review state, ledger effects,
  pricing, reporting, authorization, and audit records.
- `dclaw-client` renders server-owned values and never computes authoritative
  credits, payment amounts, prices, or balances.

The existing public website at `d-claw.deepmega.cn` and its
`dclaw-official` container are outside this change.

For Phase 1, this document supersedes the automatic-checkout goals and the
payment-channel/QR behavior in Sections 2, 7, and 8 of
`2026-08-25-credit-wallet-billing-design.md`. The wallet, ledger, pricing,
credit-lot, and settlement rules in that earlier design remain authoritative.

## 2. Confirmed Product Decisions

- DClaw owns customer-facing prices. Supplier discounts and promotions do not
  alter customer prices.
- Supplier billability controls whether an AI usage item settles; the locked
  DClaw price controls how many credits settle.
- Balance insufficiency terminates an enforced operation before the supplier
  call whenever the required hold cannot be created.
- Phase 1 uses the platform's existing fixed collection QR code and manual
  administrator review.
- The QR code and payment instructions are operational configuration, served
  by the backend from `DCLAW_TOP_UP_QR_URL` and
  `DCLAW_TOP_UP_INSTRUCTIONS`. They are never embedded in the client bundle.
- Phase 1 does not integrate WeChat Pay or Alipay APIs, process payment
  callbacks, automatically grant credits, or issue cash refunds.
- A customer payment claim is not money confirmation. Only an authenticated
  administrator can approve it.
- Approval can create its financial effect exactly once. Repeated requests,
  retries, and concurrent reviewers cannot double-credit a wallet.

## 3. Scope

### 3.1 Customer capabilities

- Persistent balance badge showing available and held credits.
- Wallet overview with available, held, purchased, and promotional credit
  breakdowns where the backend can supply them.
- Server-configured fixed top-up products.
- Collection QR code and instructions.
- Top-up claim submission and status history.
- Append-only wallet ledger with customer-safe metadata.
- OpenAPI usage-order list, detail, and UTC daily/monthly summary.
- Low-balance and insufficient-credit guidance linking to the wallet.

### 3.2 Administrator capabilities

- Top-up claim queue and detail.
- Approve or reject with a mandatory reason.
- Review actor derived from authenticated request state, never request data.
- Immutable review audit and financial ledger reference.
- Existing price-catalog draft/publish UI.
- Existing wallet, usage, reconciliation, audit, and rollout views.
- No direct balance-edit field or endpoint.

### 3.3 Explicitly deferred

- Automatic payment channels and callbacks.
- Cash refunds, chargebacks, or automatic reconciliation with a payment
  provider.
- Arbitrary customer-entered payment amounts.
- Enterprise/shared wallets.
- Ordinary DClaw chat metering and UI.
- AIGC Studio image, video, and audio metering and UI.
- Claims that attempt to infer a successful payment from a screenshot or
  client-submitted value.

Ordinary chat and AIGC billing form Phase 2 because their server request paths
do not yet run inside the durable billing context. Phase 1 must not label those
operations as charged or display fabricated estimates for them.

## 4. Top-up Products

Products are backend records rather than TypeScript constants. A product has:

- stable public ID;
- display name;
- payment amount in integer fen;
- permanent purchased credits;
- optional promotional credits and expiry days;
- display order and enabled state;
- created and updated timestamps.

Initial seed products retain the confirmed commercial table:

| Payment | Purchased credits | 90-day promotional credits | Total |
| ---: | ---: | ---: | ---: |
| CNY 10 | 1,000 | 0 | 1,000 |
| CNY 50 | 5,000 | 300 | 5,300 |
| CNY 100 | 10,000 | 1,000 | 11,000 |
| CNY 500 | 50,000 | 7,500 | 57,500 |
| CNY 1,000 | 100,000 | 20,000 | 120,000 |

A claim stores an immutable product snapshot. Later product edits cannot alter
the amount or credits under review.

Phase 1 administrator UI may enable, disable, reorder, and replace products.
A used product is never destructively edited; replacement creates a new
version or stable record while existing snapshots remain unchanged.

## 5. Data Model

### 5.1 `billing_top_up_products`

- `id` UUID primary key
- `public_id` unique opaque identifier
- `name`
- `payment_amount_fen` positive BIGINT
- `purchased_credits` positive BIGINT
- `promotional_credits` non-negative BIGINT
- `promotional_expiry_days` nullable positive integer
- `enabled` boolean
- `display_order` integer
- `created_at`, `updated_at`

### 5.2 `billing_top_up_claims`

- `id` UUID primary key
- `public_id` unique opaque customer-facing identifier
- `wallet_id` foreign key
- `owner_type`, `owner_id` ownership snapshot
- `product_id` nullable foreign key
- `product_snapshot_json` canonical immutable snapshot
- `payment_channel` allowlisted value such as `wechat` or `alipay`
- `payer_reference` customer-supplied last digits or transfer reference
- `paid_at` customer-declared timestamp
- `note` bounded customer text
- `evidence_asset_id` optional authenticated private asset reference
- `status`: `pending`, `approved`, `rejected`
- `submitted_at`, `reviewed_at`
- `reviewed_by`, `review_reason`
- `ledger_business_key` unique nullable value set on approval
- `request_hash` canonical submission hash

The database rejects invalid state combinations. Pending claims have no review
or ledger fields. Approved claims have reviewer, reason, reviewed timestamp,
and ledger business key. Rejected claims have reviewer, reason, and reviewed
timestamp but no financial key.

### 5.3 `billing_top_up_audits`

An append-only audit records submission, approval, rejection, replay, and
conflict outcomes. It contains claim ID, authenticated actor, action,
idempotency key, request hash, prior/new state, timestamp, and financial ledger
reference where applicable. SQLite and PostgreSQL prevent update and delete.

The audit never treats customer evidence as proof of payment and never exposes
private evidence through customer APIs.

## 6. State and Financial Invariants

1. A user can submit a claim only for their own active wallet and an enabled
   product returned by the backend.
2. The server copies the selected product snapshot; customer input cannot
   supply money or credit amounts.
3. A claim moves from `pending` to exactly one of `approved` or `rejected`.
4. Only an authenticated administrator can review a pending claim.
5. Approval and the following operations occur in one database transaction:
   lock claim, validate pending, append audit, grant purchased/promotional
   lots, append ledger entries, update wallet projection, mark approved.
6. Approval uses a claim-scoped unique business key and an administrator
   `Idempotency-Key`. Exact replay returns the prior result; payload drift
   returns `409`.
7. Concurrent approvals have one winner and one idempotent read/conflict; they
   never create two grants.
8. Rejection has no wallet or ledger effect.
9. No API writes available/held balance columns directly.
10. Promotional bonus lots use the snapshot expiry; purchased lots never
    expire.
11. A mistaken approval is corrected only with a compensating audited ledger
    entry in a later operational workflow, never by editing or deleting the
    original grant. Phase 1 UI does not expose reversal.

## 7. APIs

All customer routes use the authenticated user from request state. All admin
routes require the existing admin dependency.

### 7.1 Customer

- `GET /api/billing/wallet`
- `GET /api/billing/ledger`
- `GET /api/billing/usage-orders`
- `GET /api/billing/usage-orders/{order_id}`
- `GET /api/billing/open-api-summary`
- `GET /api/billing/top-up/config`
  - QR URL, instructions, enabled flag, `collects_payment=false`
- `GET /api/billing/top-up/products`
- `POST /api/billing/top-up/claims`
  - accepts product public ID, channel, payer reference, paid-at, note, and
    optional private evidence reference
  - requires `Idempotency-Key`
- `GET /api/billing/top-up/claims`
- `GET /api/billing/top-up/claims/{claim_public_id}`

Customer serializers expose public IDs and safe statuses only. They exclude
wallet IDs, internal product/claim IDs, administrator IDs, ledger business
keys, request hashes, supplier evidence, and internal asset paths.

### 7.2 Administrator

- `GET /api/admin/billing/top-up/products`
- `POST /api/admin/billing/top-up/products`
- `PATCH /api/admin/billing/top-up/products/{public_id}`
- `GET /api/admin/billing/top-up/claims`
- `GET /api/admin/billing/top-up/claims/{public_id}`
- `POST /api/admin/billing/top-up/claims/{public_id}/approve`
- `POST /api/admin/billing/top-up/claims/{public_id}/reject`
- `GET /api/admin/billing/top-up/audits`
- `GET /api/admin/billing/top-up/audits/{audit_id}`

Approve/reject require `Idempotency-Key` and a non-empty reason. Approval does
not accept an amount or credit count; it uses the stored snapshot.

## 8. Customer UI

### 8.1 Shared balance badge

- Display available credits in the authenticated client header/sidebar.
- Show held credits in a tooltip or detail popover.
- Low balance uses the server's threshold and links to `/wallet`.
- Refresh after top-up status changes, billing terminal events, and manual
  user refresh.
- API errors show an unavailable state rather than a fabricated zero.

### 8.2 Wallet page

Sections:

1. Balance overview.
2. Recharge products with permanent and promotional credits clearly split.
3. QR and payment instructions returned by the server.
4. Claim form. Money and credits are read-only product values.
5. Claim history with pending/approved/rejected status and review reason.
6. Ledger with event and date filters.
7. OpenAPI usage orders and detail drawer.
8. UTC daily/monthly consumption summary.

Submitting a claim requires a confirmation that payment is subject to manual
review and does not instantly grant credits. Double-click and retry reuse the
same idempotency key until the request resolves.

### 8.3 Insufficient-credit experience

When an existing enforced OpenAPI flow returns `insufficient_credits`, the UI
shows remaining and required credits from the sealed backend response and
links to `/wallet`. It does not retry automatically after a top-up.

## 9. Administrator UI

Add Billing settings with independently testable tabs:

- Overview and rollout mode.
- Price catalogs.
- Top-up products and QR configuration status.
- Pending/all top-up claims.
- Wallet and customer-safe/full-admin ledger views.
- Usage orders and details.
- Reconciliation queue and immutable audits.

Claim approval displays the immutable product snapshot, customer reference,
declared payment time, private evidence through an authenticated preview, and
existing wallet context. It requires a reason and explicit confirmation. The
screen has no arbitrary balance or credit input.

The QR URL and instructions are display-only in Phase 1 admin UI. Operators
maintain them through protected deployment configuration. This avoids turning
an ordinary settings endpoint into an unaudited redirect or content-injection
surface.

## 10. Security and Privacy

- Evidence assets are private and ownership/admin checked.
- Customer text fields have strict lengths and render as text, never HTML.
- QR URLs accept only configured HTTPS URLs; the client does not accept or
  construct a QR target from query parameters.
- Customer APIs use 404 for foreign claim/order identifiers.
- Admin reason and actor are stored; actor cannot be supplied by payload.
- User ledger and claim DTOs use explicit allowlists.
- Money uses integer fen and credits use BIGINT.
- Secrets, supplier references, hashes, internal IDs, and private storage paths
  never enter customer DTOs or frontend logs.
- Rate limits apply to claim creation; one user cannot create an unbounded
  pending queue.

## 11. Failure Handling

- Missing QR/config returns `enabled=false`; the wallet remains readable but
  claim submission is disabled.
- Disabled/deleted product selection returns `409 product_unavailable`.
- Duplicate submission with identical idempotency data returns the original
  claim; drift returns `409 idempotency_conflict`.
- Already reviewed claim returns its existing result for exact replay and
  `409 claim_already_reviewed` for a conflicting action.
- Approval ledger failure rolls back claim state and audit together.
- Unknown network outcome is recovered by listing claims; the client does not
  create a new key automatically.
- Pagination cursors are opaque and filter scoped.

## 12. Testing

### 12.1 Server

- Fresh and legacy SQLite/PostgreSQL schema upgrade twice.
- Product constraints and immutable snapshots.
- Customer ownership and foreign-ID 404.
- Submission replay/drift and pending limits.
- Approval/rejection state machine.
- Concurrent approval single financial winner on PostgreSQL.
- Transaction rollback under injected ledger/audit failure.
- Purchased non-expiry and promotional expiry.
- Immutable audit update/delete rejection.
- Serializer redaction and QR URL validation.
- Existing wallet, OpenAPI billing, reconciliation, and ledger regressions.

### 12.2 Client

- Typed API paths and DTO handling.
- Balance loading, low balance, held balance, and unavailable state.
- Product permanent/bonus/expiry copy.
- QR disabled/enabled states.
- Claim confirmation, idempotent double click, retry recovery, and statuses.
- Customer ledger and usage detail.
- Admin approval/rejection, mandatory reason, masked private fields, and no
  direct credit editor.
- Permission boundaries and foreign 404.
- Full typecheck, lint, unit tests, and production build.

### 12.3 Cross-repository acceptance

Build the server image with `dclaw-client/console` injected into the build
context. Against isolated PostgreSQL and Redis, prove:

1. existing user receives wallet view;
2. user submits one claim;
3. concurrent duplicate admin approval creates one grant;
4. user sees approved claim and increased balance;
5. ledger reconstructs the projection;
6. OpenAPI usage consumes the credited balance;
7. foreign users cannot read the claim;
8. rollback to the old image remains possible without restoring the database
   because new tables are additive.

## 13. Deployment

- Implement on isolated worktrees in both repositories; preserve the dirty
  `dclaw-client` main checkout.
- Push reviewed server and client commits to their respective `main` branches
  only after explicit approval.
- Build one application image from pinned server and client SHAs.
- Reuse the production PostgreSQL, Redis, data, secret, and backup volumes.
- Take a fresh pre-switch PostgreSQL dump and retain the old application image
  and stopped container.
- Start in `shadow` mode. Manual top-up approval may be enabled independently;
  OpenAPI enforcement remains governed by the existing explicit rollout CAS.
- Rollback normally restores the old application container without reversing
  additive schema. Restore the database only for proven migration corruption,
  not for ordinary application rollback.

## 14. Success Criteria

- A customer can submit and track a fixed-product top-up claim without
  supplying authoritative money or credits.
- One approved claim produces exactly one audited wallet grant.
- A rejected claim produces no financial effect.
- Customers can understand balance, ledger, and OpenAPI consumption without
  seeing internal evidence or identifiers.
- Administrators can review top-ups, pricing, usage, reconciliation, and
  rollout without a direct balance editor.
- The combined server/client image passes production build and PostgreSQL
  acceptance tests.
- Ordinary chat and AIGC are clearly not represented as billed until Phase 2.
