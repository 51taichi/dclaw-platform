# Credit Accounting Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PostgreSQL-backed personal wallet, immutable credit ledger, credit-lot allocation, versioned retail catalog, and shadow-quote APIs without charging production users.

**Architecture:** A focused `billing` package owns accounting models and transactions. Repositories persist normalized rows; services enforce invariants; routers expose user/admin contracts. Billing starts in `shadow` mode so quotes and usage orders are recorded without debits.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy Core 2.x, PostgreSQL/SQLite compatibility, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-credit-wallet-billing-design.md`

## Global Constraints

- 100 credits represent approximately CNY 1 of DClaw service value.
- DClaw's published price catalog is the only customer retail-price authority.
- Ledger history is append-only; balances cannot be overwritten directly.
- Wallet owner shape is `(owner_type, owner_id)` and first release uses `owner_type=user`.
- Credit and fen values are integers; available balance must never be negative.
- PostgreSQL is authoritative; SQLite remains supported by repository tests.
- Billing enforcement defaults to `shadow`, not `enforced`.

---

### Task 1: Durable accounting schema

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Test: `tests/unit/app/storage/test_billing_schema.py`

**Interfaces:**
- Produces tables: `billing_wallets`, `billing_credit_lots`, `billing_ledger_entries`, `billing_ledger_allocations`, `billing_price_catalogs`, `billing_price_rules`, `billing_usage_orders`, `billing_usage_items`.
- Produces unique keys: wallet owner, ledger idempotency key, usage business key, catalog version.

- [ ] **Step 1: Write a failing schema test** that calls `create_all(engine)` twice and asserts all eight tables, the owner uniqueness constraint, integer amount columns, and foreign keys exist.

```python
def test_billing_schema_is_idempotent(sqlite_engine):
    create_all(sqlite_engine)
    create_all(sqlite_engine)
    names = set(inspect(sqlite_engine).get_table_names())
    assert {"billing_wallets", "billing_credit_lots", "billing_ledger_entries",
            "billing_ledger_allocations", "billing_price_catalogs",
            "billing_price_rules", "billing_usage_orders",
            "billing_usage_items"} <= names
```

- [ ] **Step 2: Verify red.** Run `pytest tests/unit/app/storage/test_billing_schema.py -q`; expect missing-table failure.
- [ ] **Step 3: Add the SQLAlchemy tables and indexes** with UUID-string IDs, timezone timestamps, JSON stored as `Text`, integer credits/fen, and explicit status strings. Add no organization table.
- [ ] **Step 4: Verify green.** Run `pytest tests/unit/app/storage/test_billing_schema.py -q` and `pytest tests/unit/app/storage -q`.
- [ ] **Step 5: Commit.** `git add src/qwenpaw/app/storage/schema.py tests/unit/app/storage/test_billing_schema.py && git commit -m "feat: add credit accounting schema"`

### Task 2: Wallet repository and projection invariants

**Files:**
- Create: `src/qwenpaw/app/billing/models.py`
- Create: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Test: `tests/unit/app/storage/repos/test_billing_repo.py`

**Interfaces:**
- Produces `WalletBalance(available: int, held: int, purchased: int, promotional: int, package: int)`.
- Produces `BillingRepository.ensure_wallet(owner_type: str, owner_id: str) -> dict`.
- Produces `BillingRepository.append_transaction(command: LedgerTransaction) -> WalletBalance`.
- Produces `BillingRepository.list_ledger(wallet_id: str, limit: int, cursor: str | None) -> list[dict]`.

- [ ] **Step 1: Write failing tests** for wallet idempotency, duplicate ledger idempotency rejection, earliest-expiry allocation, promotional-before-purchased allocation, exact release restoration, and negative-balance rejection.

```python
def test_debit_uses_expiring_promotional_lot_first(repo):
    wallet = repo.ensure_wallet("user", "18")
    repo.grant(wallet["id"], credits=100, credit_type="purchased", expires_at=None, idempotency_key="p")
    repo.grant(wallet["id"], credits=30, credit_type="promotional", expires_at=soon(), idempotency_key="g")
    repo.hold(wallet["id"], credits=40, business_key="job-1", idempotency_key="h")
    assert repo.allocations("job-1") == [("g", 30), ("p", 10)]
```

- [ ] **Step 2: Verify red.** Run `pytest tests/unit/app/storage/repos/test_billing_repo.py -q`.
- [ ] **Step 3: Implement typed commands and repository transactions.** Use `engine.begin()`, deterministic lot ordering, compensating entries, and cached totals updated in the same transaction.
- [ ] **Step 4: Verify green on SQLite and PostgreSQL integration fixture.** Run `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/integration -k billing -q`.
- [ ] **Step 5: Commit.** `git add src/qwenpaw/app/billing src/qwenpaw/app/storage/repos/billing_repo.py tests/unit/app/storage/repos/test_billing_repo.py && git commit -m "feat: add wallet ledger repository"`

### Task 3: Wallet service and signup trial policy

**Files:**
- Create: `src/qwenpaw/app/billing/service.py`
- Create: `src/qwenpaw/app/billing/policies.py`
- Modify: `src/qwenpaw/app/routers/admin_users.py`
- Test: `tests/unit/app/billing/test_wallet_service.py`
- Test: `tests/unit/app/routers/test_admin_users_repo.py`

**Interfaces:**
- Produces `WalletService.get_or_create_personal_wallet(user_id: int) -> WalletBalance`.
- Produces `WalletService.grant_signup_trial(user_id: int, verified_mobile: str, risk_key: str) -> GrantResult`.
- Trial policy: 100 promotional credits, seven-day expiry, one grant per risk identity, capability restrictions stored in lot metadata.

- [ ] **Step 1: Write failing tests** proving existing users get one wallet, repeated trial requests grant once, an unverified mobile grants nothing, and metadata excludes video/high-cost capabilities.
- [ ] **Step 2: Verify red.** Run `pytest tests/unit/app/billing/test_wallet_service.py -q`.
- [ ] **Step 3: Implement service and policy.** Do not grant trial credits merely on user creation; invoke only from a verified-mobile completion hook or explicit admin test path.
- [ ] **Step 4: Verify green.** Run the two test files above.
- [ ] **Step 5: Commit.** `git add src/qwenpaw/app/billing src/qwenpaw/app/routers/admin_users.py tests/unit/app && git commit -m "feat: add personal wallet service"`

### Task 4: Versioned retail catalog and quote engine

**Files:**
- Create: `src/qwenpaw/app/billing/pricing.py`
- Create: `src/qwenpaw/app/storage/repos/price_catalog_repo.py`
- Test: `tests/unit/app/billing/test_pricing.py`

**Interfaces:**
- Produces `QuoteRequest(provider_id, model_key, capability, parameters, input_tokens=0, output_tokens=0)`.
- Produces `RetailQuote(catalog_version, rule_id, credits, unit_breakdown, snapshot)`.
- Produces `PriceCatalogService.quote(request: QuoteRequest, at: datetime | None = None) -> RetailQuote`.

- [ ] **Step 1: Write failing tests** for input/output token rates, image count, video duration, fixed workflow price, exact parameter precedence, ambiguous-rule publication rejection, and immutable old quotes.

```python
def test_existing_quote_keeps_published_price(service):
    first = service.quote(QuoteRequest("aliyun", "wan-2.7", "text_to_image", {"count": 1}))
    service.publish(next_catalog(image_credits=80))
    assert first.credits == 50
    assert service.quote(first.request).credits == 80
```

- [ ] **Step 2: Verify red.** Run `pytest tests/unit/app/billing/test_pricing.py -q`.
- [ ] **Step 3: Implement draft validation, publication, lookup, integer rounding, and snapshot serialization.** Seed prices through an explicit admin command, never application constants.
- [ ] **Step 4: Verify green.** Run `pytest tests/unit/app/billing/test_pricing.py -q`.
- [ ] **Step 5: Commit.** `git add src/qwenpaw/app/billing/pricing.py src/qwenpaw/app/storage/repos/price_catalog_repo.py tests/unit/app/billing/test_pricing.py && git commit -m "feat: add versioned retail pricing"`

### Task 5: Shadow usage orders and wallet APIs

**Files:**
- Create: `src/qwenpaw/app/billing/usage.py`
- Create: `src/qwenpaw/app/routers/billing.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/routers/test_billing.py`

**Interfaces:**
- Produces `UsageService.create_quote(...)`, `hold(...)`, `capture(...)`, `release(...)`, `mark_reconciling(...)`.
- User endpoints: `GET /api/user/billing/wallet`, `GET /api/user/billing/ledger`, `POST /api/user/billing/quotes`.
- Admin endpoints: catalog draft/publish/list and wallet/ledger lookup.
- Environment: `DCLAW_BILLING_MODE=off|shadow|enforced`, default `shadow`.

- [ ] **Step 1: Write failing API tests** for user isolation, admin visibility, price snapshot responses, shadow mode recording without balance mutation, and enforced mode insufficient-balance response.
- [ ] **Step 2: Verify red.** Run `pytest tests/unit/app/routers/test_billing.py -q`.
- [ ] **Step 3: Implement routers and state machine.** Return HTTP 409 with code `insufficient_credits`; never accept client wallet IDs or prices.
- [ ] **Step 4: Run focused and regression tests.** Run `pytest tests/unit/app/routers/test_billing.py tests/unit/app/billing tests/unit/app/storage/repos/test_billing_repo.py -q`.
- [ ] **Step 5: Commit.** `git add src/qwenpaw/app/billing src/qwenpaw/app/routers tests/unit/app && git commit -m "feat: expose shadow credit accounting APIs"`
