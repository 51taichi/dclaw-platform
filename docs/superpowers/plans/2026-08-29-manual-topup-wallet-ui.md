# DClaw Manual Top-up Wallet UI Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a customer wallet and fixed-QR manual top-up workflow with audited administrator approval, OpenAPI consumption views, and no direct balance editing.

**Architecture:** `dclaw-server` remains authoritative for products, claim snapshots, review state, ledger effects, prices, balances, reporting, and authorization. `dclaw-client` renders typed server DTOs and submits opaque product/claim identifiers; it never computes money, credits, or financial state. Server and client are developed in isolated worktrees and combined only in the final image acceptance task.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, PostgreSQL 16, SQLite compatibility, React 18, TypeScript 5.8, Ant Design 5, React Router 7, Vitest/Testing Library, Vite 6, Docker.

**Spec:** `docs/superpowers/specs/2026-08-29-manual-topup-wallet-ui-design.md`

## Global Constraints

- Use isolated worktrees for both repositories. Preserve the dirty `dclaw-client/main` checkout.
- Use TDD: each behavior test must fail for the intended missing behavior before production code is written.
- The server owns every payment amount, credit amount, expiry, balance, and status.
- Approval appends ledger/lot effects; no API updates balance projection fields directly.
- QR and instructions come only from `DCLAW_TOP_UP_QR_URL` and `DCLAW_TOP_UP_INSTRUCTIONS` in Phase 1.
- Customer DTOs exclude internal IDs, request hashes, business keys, private asset paths, supplier references, and administrator identities.
- Administrator actor comes from authenticated request state, never a payload field.
- All financial integers use BIGINT; money uses integer fen.
- Automatic payment, refunds, ordinary chat billing, and AIGC billing are out of scope.
- The existing `dclaw-official` website/container is not modified.
- Every server schema change must support fresh and legacy SQLite and PostgreSQL and remain idempotent across two bootstraps.

---

### Task 1: Durable top-up products, claims, and immutable audits

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Create: `src/qwenpaw/app/storage/repos/top_up_repo.py`
- Modify: `src/qwenpaw/app/storage/bootstrap.py`
- Create: `tests/unit/app/storage/repos/test_top_up_repo.py`
- Modify: `tests/unit/app/storage/test_billing_schema.py`
- Modify: `tests/integration/test_billing_schema_postgres.py`
- Create: `tests/integration/test_top_up_repo_postgres.py`

**Interfaces:**
- Produces: `TopUpRepository(engine)`.
- Produces: `create_product`, `list_products`, `replace_product`, `create_claim`, `get_claim_by_public_id`, `list_claims`, `lock_pending_claim`, `append_audit`, and `list_audits`.
- Produces canonical product snapshots with `payment_amount_fen`, `purchased_credits`, `promotional_credits`, and `promotional_expiry_days`.
- Consumes the existing SQLAlchemy engine and UTC timestamp conventions.

- [ ] **Step 1: Write fresh/legacy schema RED tests**

Add assertions for `billing_top_up_products`, `billing_top_up_claims`, and
`billing_top_up_audits`, including BIGINT columns, ownership/product foreign
keys, unique `public_id`, unique nullable `ledger_business_key`, state checks,
and audit update/delete rejection:

```python
def test_top_up_schema_rejects_approved_claim_without_financial_key(engine):
    create_all(engine)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text("""
                INSERT INTO billing_top_up_claims
                    (id, public_id, wallet_id, owner_type, owner_id,
                     product_snapshot_json, payment_channel, payer_reference,
                     status, reviewed_by, review_reason, reviewed_at)
                VALUES
                    ('c1', 'claim-public', 'wallet-1', 'user', 'u1', '{}',
                     'wechat', '1234', 'approved', 'admin-1', 'ok', CURRENT_TIMESTAMP)
            """),
        )
```

- [ ] **Step 2: Run schema tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/app/storage/test_billing_schema.py \
  tests/integration/test_billing_schema_postgres.py -q
```

Expected: failures because the three tables and constraints do not exist.

- [ ] **Step 3: Add tables, indexes, and immutable triggers**

Use SQLAlchemy metadata for fresh tables. Extend the existing dialect-aware
bootstrap for legacy databases. Install SQLite and PostgreSQL audit
update/delete guards idempotently. Validate existing data before tightening
constraints. Seed no claim or audit data.

- [ ] **Step 4: Write repository RED tests**

Cover opaque UUID public IDs, immutable product snapshots, filter-scoped
pagination, owner isolation, exact replay/request-hash drift, and concurrent
pending-claim locks:

```python
def test_claim_keeps_product_snapshot_after_product_replacement(repo):
    product = repo.create_product(product_fixture(payment_amount_fen=1000))
    claim = repo.create_claim(claim_fixture(product=product))
    repo.replace_product(product["public_id"], product_fixture(payment_amount_fen=5000))
    stored = repo.get_claim_by_public_id(claim["public_id"])
    assert stored["product_snapshot"]["payment_amount_fen"] == 1000
```

- [ ] **Step 5: Run repository tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/app/storage/repos/test_top_up_repo.py \
  tests/integration/test_top_up_repo_postgres.py -q
```

Expected: import/attribute failures for `TopUpRepository`.

- [ ] **Step 6: Implement the minimal repository**

Keep serialization in `top_up_repo.py`. Use canonical JSON and stable request
hashes. PostgreSQL review paths use `SELECT ... FOR UPDATE`; SQLite uses its
existing serialized-writer transaction pattern. Repository methods accept an
optional caller-owned connection for Task 2 atomic approval.

- [ ] **Step 7: Run fresh, legacy, and PostgreSQL tests**

Run:

```bash
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest \
  tests/unit/app/storage/test_billing_schema.py \
  tests/unit/app/storage/repos/test_top_up_repo.py \
  tests/integration/test_billing_schema_postgres.py \
  tests/integration/test_top_up_repo_postgres.py -q
```

Expected: all pass; PostgreSQL tests use isolated schemas and clean them.

- [ ] **Step 8: Commit**

```bash
git add src/qwenpaw/app/storage tests/unit/app/storage tests/integration/test_billing_schema_postgres.py tests/integration/test_top_up_repo_postgres.py
git commit -m "feat: add durable manual top-up records"
```

---

### Task 2: Manual top-up state machine and authenticated APIs

**Files:**
- Create: `src/qwenpaw/app/billing/top_up.py`
- Modify: `src/qwenpaw/app/routers/billing.py`
- Modify: `src/qwenpaw/app/billing/models.py`
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Create: `tests/unit/app/billing/test_top_up_service.py`
- Modify: `tests/unit/app/routers/test_billing.py`
- Modify: `tests/integration/test_top_up_repo_postgres.py`

**Interfaces:**
- Consumes: `TopUpRepository` from Task 1 and the existing append-only wallet/lot ledger primitive.
- Produces: `TopUpService.submit_claim(owner_id, command)`, `approve_claim(public_id, actor_id, command)`, `reject_claim(...)`, `list_customer_claims`, and `list_admin_claims`.
- Produces customer routes under `/api/user/billing/top-up/*` and admin routes under `/api/admin/billing/top-up/*`.
- Approval command includes only `idempotency_key` and `reason`; it never accepts amount or credits.

- [ ] **Step 1: Write state-machine RED tests**

```python
def test_approval_uses_snapshot_and_grants_once(service, repo):
    claim = service.submit_claim("user-1", submit_command("product-10"))
    first = service.approve_claim(
        claim.public_id,
        "admin-1",
        ReviewCommand(idempotency_key="approve-1", reason="bank receipt verified"),
    )
    replay = service.approve_claim(
        claim.public_id,
        "admin-1",
        ReviewCommand(idempotency_key="approve-1", reason="bank receipt verified"),
    )
    assert first == replay
    assert repo.balance(first.wallet_id).available == 1000
    assert count_grant_entries(repo, first.wallet_id) == 1
```

Add tests for rejected/no-effect, actor spoof rejection, disabled product,
foreign owner 404, submission idempotency drift, approval-vs-rejection race,
injected audit/ledger rollback, permanent purchased lot, expiring bonus lot,
and pending-claim per-user limit.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/app/billing/test_top_up_service.py -q
```

Expected: missing `qwenpaw.app.billing.top_up`.

- [ ] **Step 3: Implement service with one approval transaction**

Create immutable dataclass commands. Approval order is: lock claim, replay/hash
check, validate pending, append audit, append purchased grant, append optional
promotional grant, update projections, transition claim. Reuse the wallet
ledger primitive and claim-scoped business key. Any exception rolls back all
effects.

- [ ] **Step 4: Write API RED tests**

Use a real FastAPI test app with authentication dependencies. Assert exact
route prefixes and safe DTOs:

```python
def test_customer_cannot_supply_credit_amount(client, user_headers):
    response = client.post(
        "/api/user/billing/top-up/claims",
        headers={**user_headers, "Idempotency-Key": "claim-1"},
        json={"product_id": "p10", "purchased_credits": 999999},
    )
    assert response.status_code == 422
```

Cover config `enabled=false`, HTTPS QR allowlist, customer/internal-field
redaction, admin reason required, admin actor from auth, audit list/detail,
pagination, and 409 codes.

- [ ] **Step 5: Run router tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/app/routers/test_billing.py -q
```

Expected: new routes return 404 or models reject imports.

- [ ] **Step 6: Implement API models and routes**

Add explicit Pydantic `extra="forbid"` request models and allowlist response
serializers. Validate QR as configured HTTPS only. Add product seed bootstrap
that inserts the five initial products only when no products exist; repeated
startup does not overwrite operator replacements.

- [ ] **Step 7: Run PostgreSQL financial race tests**

Run:

```bash
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest \
  tests/unit/app/billing/test_top_up_service.py \
  tests/unit/app/routers/test_billing.py \
  tests/integration/test_top_up_repo_postgres.py -q
```

Expected: concurrent approval has one financial winner; exact replay returns
the winner; reject race cannot create a grant.

- [ ] **Step 8: Commit**

```bash
git add src/qwenpaw/app/billing src/qwenpaw/app/routers/billing.py src/qwenpaw/app/storage/repos/billing_repo.py tests/unit/app/billing/test_top_up_service.py tests/unit/app/routers/test_billing.py tests/integration/test_top_up_repo_postgres.py
git commit -m "feat: add audited manual top-up workflow"
```

---

### Task 3: Typed client API and shared balance state

**Files (in the `dclaw-client` worktree):**
- Create: `console/src/api/types/billing.ts`
- Create: `console/src/api/modules/billing.ts`
- Create: `console/src/api/modules/billing.test.ts`
- Modify: `console/src/api/types/index.ts`
- Modify: `console/src/api/index.ts`
- Modify: `console/src/api/config.ts`
- Create: `console/src/features/billing/useBillingWallet.ts`
- Create: `console/src/features/billing/BalanceBadge.tsx`
- Create: `console/src/features/billing/BalanceBadge.test.tsx`
- Modify: `console/src/layouts/Header.tsx`

**Interfaces:**
- Consumes the customer/admin routes from Task 2 and existing billing reporting routes.
- Produces `billingApi` with wallet, ledger, usage, summary, products, config, claims, admin reviews, catalogs, reconciliation, and rollout methods.
- Produces `useBillingWallet()` returning `{ wallet, loading, unavailable, refresh }`.

- [ ] **Step 1: Write API routing RED tests**

```typescript
it("routes customer and admin billing requests through separate namespaces", async () => {
  await billingApi.getWallet();
  await billingApi.listAdminClaims({ limit: 20 });
  expect(request).toHaveBeenNthCalledWith(1, "/billing/wallet", expect.anything());
  expect(request).toHaveBeenNthCalledWith(2, "/admin/billing/top-up/claims?limit=20", expect.anything());
});
```

Also assert integer DTOs, opaque cursors, `Idempotency-Key`, and stable 409
error-code parsing.

- [ ] **Step 2: Run API tests and verify RED**

Run from `console`:

```bash
npm test -- --run src/api/modules/billing.test.ts
```

Expected: missing billing module/types.

- [ ] **Step 3: Implement types and API module**

Add `/billing` to user prefix routing without misrouting explicit
`/admin/billing`. Use existing `request` and auth header conventions. Do not
add rate tables, conversion helpers, or frontend-derived balances.

- [ ] **Step 4: Write balance badge RED tests**

Cover available, held tooltip, loading, server-unavailable display, low-balance
link, and refresh after a custom `dclaw:billing-settled` event.

- [ ] **Step 5: Run balance tests and verify RED**

```bash
npm test -- --run src/features/billing/BalanceBadge.test.tsx
```

Expected: missing component/hook.

- [ ] **Step 6: Implement shared hook and badge**

Use one deduplicated request per mounted header. Render `--` on unavailable,
never zero. Keep event refresh bounded/debounced. Add accessible labels for
available and held credits.

- [ ] **Step 7: Run client quality checks**

```bash
npm test -- --run src/api/modules/billing.test.ts src/features/billing/BalanceBadge.test.tsx
npm run format:check
npm run lint
```

- [ ] **Step 8: Commit in client repository**

```bash
git add console/src/api console/src/features/billing console/src/layouts/Header.tsx
git commit -m "feat: add billing API and balance badge"
```

---

### Task 4: Customer wallet, claims, ledger, and OpenAPI consumption page

**Files (in the `dclaw-client` worktree):**
- Create: `console/src/pages/Wallet/index.tsx`
- Create: `console/src/pages/Wallet/index.module.less`
- Create: `console/src/pages/Wallet/WalletPage.test.tsx`
- Create: `console/src/pages/Wallet/components/TopUpPanel.tsx`
- Create: `console/src/pages/Wallet/components/ClaimHistory.tsx`
- Create: `console/src/pages/Wallet/components/LedgerTable.tsx`
- Create: `console/src/pages/Wallet/components/UsageOrders.tsx`
- Modify: `console/src/layouts/ClientLayout/index.tsx`
- Modify: `console/src/layouts/ClientLayout.test.tsx`
- Modify: `console/src/layouts/Sidebar.tsx`

**Interfaces:**
- Consumes `billingApi` and `useBillingWallet` from Task 3.
- Produces `/wallet` customer route and sidebar entry.
- Dispatches `dclaw:billing-settled` after an approved claim is observed.

- [ ] **Step 1: Write route and page RED tests**

Test the real route, product cards, permanent/bonus/expiry wording, QR disabled
and enabled states, server-owned amounts, confirmation copy, pending/approved/
rejected claims, review reason, ledger pagination, usage detail drawer, and UTC
summary.

```typescript
it("submits only an opaque product id and customer evidence", async () => {
  await user.click(screen.getByRole("button", { name: "提交充值申请" }));
  expect(billingApi.submitClaim).toHaveBeenCalledWith(
    expect.objectContaining({ productId: "topup-10" }),
    expect.any(String),
  );
  expect(billingApi.submitClaim.mock.calls[0][0]).not.toHaveProperty("credits");
  expect(billingApi.submitClaim.mock.calls[0][0]).not.toHaveProperty("amountFen");
});
```

- [ ] **Step 2: Run page tests and verify RED**

```bash
npm test -- --run src/pages/Wallet/WalletPage.test.tsx src/layouts/ClientLayout.test.tsx
```

Expected: wallet route/component absent.

- [ ] **Step 3: Implement wallet page in focused components**

Keep each component responsible for one remote state. Reuse the same
idempotency key while a submission is pending or recovering. After an unknown
network result, refresh claim history before offering another submission.
Never render evidence as HTML.

- [ ] **Step 4: Add insufficient-credit navigation test**

Add a shared helper/component that accepts the sealed backend
`insufficient_credits` payload and links to `/wallet`; do not wire ordinary chat
or AIGC paths in this phase.

- [ ] **Step 5: Run customer regression and build**

```bash
npm test -- --run src/pages/Wallet src/layouts/ClientLayout.test.tsx
npm run format:check
npm run lint
npm run build
```

- [ ] **Step 6: Commit in client repository**

```bash
git add console/src/pages/Wallet console/src/layouts/ClientLayout console/src/layouts/Sidebar.tsx
git commit -m "feat: add customer credit wallet"
```

---

### Task 5: Administrator billing and top-up review console

**Files (in the `dclaw-client` worktree):**
- Create: `console/src/pages/Settings/Billing/index.tsx`
- Create: `console/src/pages/Settings/Billing/BillingSettings.test.tsx`
- Create: `console/src/pages/Settings/Billing/TopUpClaimsTab.tsx`
- Create: `console/src/pages/Settings/Billing/ProductsTab.tsx`
- Create: `console/src/pages/Settings/Billing/PricingTab.tsx`
- Create: `console/src/pages/Settings/Billing/UsageTab.tsx`
- Create: `console/src/pages/Settings/Billing/ReconciliationTab.tsx`
- Create: `console/src/pages/Settings/Billing/RolloutTab.tsx`
- Modify: `console/src/layouts/AdminLayout/index.tsx`
- Modify: `console/src/layouts/Sidebar.tsx`

**Interfaces:**
- Consumes admin methods from Task 3.
- Produces `/admin/billing` route with independent tabs.
- Approval/rejection sends authenticated requests with idempotency key and reason only.

- [ ] **Step 1: Write admin UI RED tests**

Cover pending queue, immutable snapshot, private evidence preview, mandatory
reason, approval confirmation, double-click prevention, exact replay recovery,
rejection, product enable/replace, catalog draft/publish confirmation,
reconciliation resolution, audit DTO redaction, rollout activation, and the
absence of arbitrary balance/credit inputs.

```typescript
it("does not render a direct balance editor", async () => {
  renderBillingSettings();
  expect(screen.queryByLabelText(/直接修改余额/)).not.toBeInTheDocument();
  expect(screen.queryByRole("spinbutton", { name: /赠送积分/ })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run admin tests and verify RED**

```bash
npm test -- --run src/pages/Settings/Billing/BillingSettings.test.tsx
```

Expected: missing page and route.

- [ ] **Step 3: Implement independent tabs**

Each tab owns its query/loading/error/pagination state. Product forms submit
integer server fields but never change historical snapshots. Approval uses the
stored claim detail. QR configuration is read-only and tells operators which
environment variables maintain it.

- [ ] **Step 4: Wire admin route/sidebar and run tests**

```bash
npm test -- --run src/pages/Settings/Billing src/layouts/AdminLayout.test.tsx
npm run format:check
npm run lint
npm run build
```

- [ ] **Step 5: Commit in client repository**

```bash
git add console/src/pages/Settings/Billing console/src/layouts/AdminLayout console/src/layouts/Sidebar.tsx
git commit -m "feat: add billing administration console"
```

---

### Task 6: Cross-repository acceptance, build, and rollback proof

**Files:**
- Create: `tests/integration/test_manual_top_up_acceptance.py`
- Modify: `docs/operations/open-api-billing-rollout.md`
- Create: `docs/operations/manual-top-up-wallet-release.md`
- Modify: `deploy/Dockerfile` only if the accepted source-injection contract requires it
- Test: client production build and server Docker image

**Interfaces:**
- Consumes reviewed server/client commits from Tasks 1–5.
- Produces a deployable image labeled with both Git SHAs.
- Produces an additive-schema rollback runbook that reuses the existing PostgreSQL, Redis, and three DClaw volumes.

- [ ] **Step 1: Write acceptance RED test**

Against isolated PostgreSQL and Redis, prove submit → concurrent approve → one
grant → customer visibility → OpenAPI debit → ledger reconstruction → foreign
404. Assert automatic payment and ordinary chat/AIGC billing are absent.

- [ ] **Step 2: Run acceptance test and verify RED**

```bash
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest tests/integration/test_manual_top_up_acceptance.py -q
```

Expected: failure until server routes and top-up service from Tasks 1–2 exist.

- [ ] **Step 3: Run complete server verification**

```bash
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest \
  tests/unit/app/billing \
  tests/unit/app/routers/test_billing.py \
  tests/unit/app/storage/test_billing_schema.py \
  tests/unit/app/storage/repos/test_billing_repo.py \
  tests/unit/app/storage/repos/test_top_up_repo.py \
  tests/integration/test_billing_schema_postgres.py \
  tests/integration/test_billing_repo_postgres.py \
  tests/integration/test_top_up_repo_postgres.py \
  tests/integration/test_manual_top_up_acceptance.py -q
```

- [ ] **Step 4: Run complete client verification**

From the isolated client `console` worktree:

```bash
npm test -- --run src/api/modules/billing.test.ts src/features/billing src/pages/Wallet src/pages/Settings/Billing
npm run format:check
npm run lint
npm run build
```

- [ ] **Step 5: Build the combined image from pinned SHAs**

Copy the reviewed client `console` tree into the server build context excluding
`node_modules`, `dist`, and Rust `target`. Build with labels:

```bash
docker build --file deploy/Dockerfile \
  --label "com.deepmega.dclaw.server.commit=${SERVER_SHA}" \
  --label "com.deepmega.dclaw.client.commit=${CLIENT_SHA}" \
  --tag "dclaw-local:manual-topup-${SERVER_SHA:0:7}" .
```

Run the container against isolated restored data first. Assert `/`, wallet,
admin billing, OpenAPI billing, and health routes. Inspect built assets to
prove the wallet chunks exist.

- [ ] **Step 6: Write and test rollback commands**

Document the production backup path, old image/container names, exact new
container mounts/network/port/env, fresh pre-switch `pg_dump`, stop/rename/run,
health/login/wallet/OpenAPI canaries, and one-minute old-container rollback.
Do not modify `dclaw-official`.

- [ ] **Step 7: Final reviews and commits**

Request separate server and client code reviews, fix every Critical/Important,
rerun all fresh verification, then commit operational docs/acceptance in the
server repository:

```bash
git add tests/integration/test_manual_top_up_acceptance.py docs/operations
git commit -m "test: prove manual top-up wallet release"
```

- [ ] **Step 8: Integration decision**

Present both reviewed branches and SHAs. Do not merge, push, or deploy until
the user explicitly selects the integration/deployment action.
