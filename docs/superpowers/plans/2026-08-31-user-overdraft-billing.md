# User-level overdraft billing implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded `szzz_admin` complimentary path with a private per-user overdraft capability while charging and reporting every model call normally.

**Architecture:** Keep funded credit lots non-negative and introduce explicit settled and held overdraft projections on wallets. Resolve overdraft permission from the trusted payer row inside each wallet transaction, persist the funded/debt split on the immutable hold ledger entry, and make grants repay settled debt before creating spendable lots.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy Core, PostgreSQL 16, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-user-overdraft-billing-design.md`

## Global constraints

- Runtime billing code must not contain the username `szzz_admin`, an admin-role exception, or any equivalent complimentary bypass.
- `users.billing_overdraft_enabled` defaults to false and is not exposed or mutable through public/admin APIs or UI.
- Only the one-time upgrade that creates the user column backfills the existing `szzz_admin` admin row.
- Funded credit lots and funded wallet projections remain non-negative.
- Public signed available balance equals funded available minus settled debt minus held overdraft.
- Every entry point requires published pricing and records the complete charged amount.
- Normal users remain unable to spend below zero.
- Historical complimentary calls are not retroactively charged.

---

### Task 1: Persist the private capability and overdraft projections

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/db.py`
- Test: `tests/unit/app/storage/test_billing_schema.py`
- Test: `tests/integration/test_billing_schema_postgres.py`

**Interfaces:**
- Produces: `users.c.billing_overdraft_enabled: bool`.
- Produces: `billing_wallets.c.debt_credits: int` and `billing_wallets.c.held_overdraft_credits: int`.
- Produces: idempotent startup migration that returns whether the user capability column was newly created and performs the backfill only in that branch.

- [ ] **Step 1: Write failing metadata tests**

Assert exact defaults and constraints without testing SQLAlchemy itself:

```python
assert users.c.billing_overdraft_enabled.nullable is False
assert str(users.c.billing_overdraft_enabled.server_default.arg) in {"false", "0"}
assert billing_wallets.c.debt_credits.nullable is False
assert billing_wallets.c.held_overdraft_credits.nullable is False
assert {
    constraint.name for constraint in billing_wallets.constraints
} >= {
    "ck_billing_wallets_debt_nonnegative",
    "ck_billing_wallets_held_overdraft_nonnegative",
}
```

- [ ] **Step 2: Run the metadata tests and verify RED**

Run: `pytest tests/unit/app/storage/test_billing_schema.py -q`

Expected: FAIL because the three columns do not exist.

- [ ] **Step 3: Add the columns and database constraints**

Add a private boolean to `users` and two `BigInteger` wallet columns with server defaults. Add named checks:

```python
Column("billing_overdraft_enabled", Boolean, nullable=False, server_default=false())
Column("debt_credits", BigInteger, nullable=False, server_default="0")
Column("held_overdraft_credits", BigInteger, nullable=False, server_default="0")
CheckConstraint("debt_credits >= 0", name="ck_billing_wallets_debt_nonnegative")
CheckConstraint(
    "held_overdraft_credits >= 0",
    name="ck_billing_wallets_held_overdraft_nonnegative",
)
```

- [ ] **Step 4: Write failing upgrade tests for SQLite and PostgreSQL**

Create a legacy schema without the new columns, insert both `szzz_admin/admin` and a normal user, run startup migration twice, and assert:

```python
assert rows["szzz_admin"] is True
assert rows["normal"] is False
# A same-name row inserted after the first migration must not be auto-enabled.
assert newly_inserted_same_name_overdraft_enabled is False
```

The PostgreSQL integration test must also query `pg_constraint` for both new non-negative checks.

- [ ] **Step 5: Run the migration tests and verify RED**

Run: `pytest tests/unit/app/storage/test_billing_schema.py tests/integration/test_billing_schema_postgres.py -q`

Expected: FAIL because upgrade code does not add or backfill the fields.

- [ ] **Step 6: Implement the idempotent migration**

Follow the existing schema bootstrap helpers. Determine column existence before adding it; only the branch that adds `billing_overdraft_enabled` executes this one-time data migration:

```sql
UPDATE users
SET billing_overdraft_enabled = TRUE
WHERE username = 'szzz_admin' AND role = 'admin'
```

Keep that SQL confined to migration code. Add wallet columns and PostgreSQL constraints idempotently. For SQLite legacy tables, use the repository's established rebuild/add-column pattern without dropping user data.

- [ ] **Step 7: Run schema tests and commit**

Run: `pytest tests/unit/app/storage/test_billing_schema.py tests/integration/test_billing_schema_postgres.py -q`

Expected: PASS.

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/db.py \
  tests/unit/app/storage/test_billing_schema.py \
  tests/integration/test_billing_schema_postgres.py
git commit -m "feat: add private billing overdraft capability"
```

### Task 2: Expose signed wallet balances without exposing the capability

**Files:**
- Modify: `src/qwenpaw/app/billing/models.py`
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Modify: `src/qwenpaw/app/billing/usage.py`
- Modify: `src/qwenpaw/app/billing/service.py`
- Test: `tests/unit/app/storage/repos/test_billing_repo.py`
- Test: `tests/unit/app/routers/test_billing.py`

**Interfaces:**
- Produces: `WalletBalance(funded_available, held, purchased, promotional, package, debt, held_overdraft)` with property `available -> funded_available - debt - held_overdraft`.
- Produces: `BillingRepository.overdraft_enabled_in_connection(conn, wallet_id) -> bool`, resolving a user-owned wallet through `users.id` and returning false for non-user wallets or missing users.
- Produces: public wallet JSON fields `available`, `funded_available`, `debt`, and `held_overdraft`.

- [ ] **Step 1: Write failing repository and serializer tests**

Use a real SQLite repository. Set wallet projections to funded 20, debt 25, held overdraft 3 and assert literal results:

```python
assert balance.funded_available == 20
assert balance.debt == 25
assert balance.held_overdraft == 3
assert balance.available == -8
assert wallet_balance_dict(balance) == {
    "available": -8,
    "funded_available": 20,
    "held": 0,
    "debt": 25,
    "held_overdraft": 3,
    "purchased": 20,
    "promotional": 0,
    "package": 0,
}
```

Assert the capability resolver is true only for a user row with the flag set, not merely for an admin role or matching username fixture.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/routers/test_billing.py -q`

Expected: FAIL due to missing fields and resolver.

- [ ] **Step 3: Implement the typed balance and resolver**

Keep database funded available separate from the signed public property. Build `WalletBalance` from named keyword arguments at every construction site to prevent positional field drift. The resolver must use one join:

```python
select(users.c.billing_overdraft_enabled).select_from(
    billing_wallets.join(
        users,
        and_(
            billing_wallets.c.owner_type == "user",
            cast(users.c.id, String) == billing_wallets.c.owner_id,
        ),
    ),
).where(billing_wallets.c.id == wallet_id)
```

- [ ] **Step 4: Update wallet serialization**

Return signed `available` for clients and explicit funded/debt projections for auditability. Do not add `billing_overdraft_enabled` to any response model.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/routers/test_billing.py -q`

Expected: PASS.

```bash
git add src/qwenpaw/app/billing/models.py \
  src/qwenpaw/app/storage/repos/billing_repo.py \
  src/qwenpaw/app/billing/usage.py src/qwenpaw/app/billing/service.py \
  tests/unit/app/storage/repos/test_billing_repo.py \
  tests/unit/app/routers/test_billing.py
git commit -m "feat: report signed wallet balances"
```

### Task 3: Reserve, capture, and release overdraft atomically

**Files:**
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Modify: `src/qwenpaw/app/billing/models.py`
- Test: `tests/unit/app/storage/repos/test_billing_repo.py`
- Test: `tests/integration/test_billing_repo_postgres.py`

**Interfaces:**
- Produces: hold ledger metadata keys `funded_credits` and `overdraft_credits` as non-negative integers summing to the hold amount.
- Consumes: `BillingRepository.overdraft_enabled_in_connection(conn, wallet_id) -> bool` from Task 2.
- Preserves: `hold`, `capture`, and `release` public signatures and idempotency keys.

- [ ] **Step 1: Write failing behavior tests**

Cover literal scenarios using real repositories:

```python
# Enabled wallet: 3 funded, hold 8.
assert after_hold.funded_available == 0
assert after_hold.held == 3
assert after_hold.held_overdraft == 5
assert after_hold.available == -5

# Capture 8.
assert after_capture.held == 0
assert after_capture.held_overdraft == 0
assert after_capture.debt == 5
assert after_capture.available == -5

# Release the same split instead.
assert after_release.funded_available == 3
assert after_release.debt == 0
assert after_release.held_overdraft == 0
```

Also assert a normal user's 8-credit hold with only 3 funded credits raises `InsufficientCreditsError` without ledger or balance mutation. Add concurrent PostgreSQL holds whose captured total equals the exact debt increase.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/integration/test_billing_repo_postgres.py -q`

Expected: FAIL because holds reject the enabled user.

- [ ] **Step 3: Implement split hold**

Inside the existing locked transaction, allocate `funded = min(wallet_available, requested)` and `overdraft = requested - funded`. Reject nonzero overdraft unless the resolver returns true. Allocate lots only for `funded`, persist both literal amounts into the hold ledger metadata, decrement funded available only by `funded`, and increment the separate held projections.

- [ ] **Step 4: Implement split release and capture**

Read and validate the persisted split from the original hold ledger. Release only the funded lot allocations and decrement `held_overdraft_credits` by the recorded overdraft. Capture funded lots normally, move captured overdraft from held overdraft to settled debt, and write `credit_delta=-captured_total` so reporting sees the complete charge.

When actual settlement is lower than the hold, release the unused funded/debt portions deterministically. When it is higher, run the existing incremental reservation path, which creates an additional persisted split before capture.

- [ ] **Step 5: Run focused and concurrency tests**

Run: `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/integration/test_billing_repo_postgres.py -q`

Expected: PASS with no constraint or idempotency failures.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/storage/repos/billing_repo.py \
  src/qwenpaw/app/billing/models.py \
  tests/unit/app/storage/repos/test_billing_repo.py \
  tests/integration/test_billing_repo_postgres.py
git commit -m "feat: settle usage through wallet overdraft"
```

### Task 4: Repay settled debt before granting spendable credits

**Files:**
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Test: `tests/unit/app/storage/repos/test_billing_repo.py`
- Test: `tests/integration/test_billing_repo_postgres.py`
- Test: `tests/unit/app/billing/test_top_up_service.py`

**Interfaces:**
- Preserves: `grant(...) -> WalletBalance` and `append_transaction(...)` signatures.
- Produces: grant ledger metadata `debt_repaid_credits` and `funded_grant_credits`, which sum to the requested grant.
- Produces: a credit lot only for `funded_grant_credits`; zero remainder creates no empty lot.

- [ ] **Step 1: Write failing grant tests**

Seed settled debt directly through the real overdraft usage flow from Task 3, then grant literal amounts:

```python
# debt 10, grant 4 -> debt 6, funded 0, signed available -6
# debt 10, grant 10 -> debt 0, funded 0, signed available 0
# debt 10, grant 30 -> debt 0, funded 20, signed available 20
```

Replay each grant idempotency key and assert debt is repaid exactly once. Assert purchased, promotional, and package grants all use the same debt-first rule while retaining the remainder's original credit type.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/billing/test_top_up_service.py tests/integration/test_billing_repo_postgres.py -q`

Expected: FAIL because the complete grant currently becomes a funded lot.

- [ ] **Step 3: Implement debt-first grants**

Under the wallet lock compute:

```python
repaid = min(current_debt, command.credits)
funded = command.credits - repaid
```

Decrease `debt_credits` by `repaid`; create/update funded projections and a credit lot only for `funded`. Persist both values in the immutable grant ledger metadata while retaining the full positive `credit_delta` for net-balance audit math.

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/billing/test_top_up_service.py tests/integration/test_billing_repo_postgres.py -q`

Expected: PASS.

```bash
git add src/qwenpaw/app/storage/repos/billing_repo.py \
  tests/unit/app/storage/repos/test_billing_repo.py \
  tests/unit/app/billing/test_top_up_service.py \
  tests/integration/test_billing_repo_postgres.py
git commit -m "feat: repay wallet debt before credit grants"
```

### Task 5: Remove complimentary pricing and enforce uniform billing

**Files:**
- Delete: `src/qwenpaw/app/billing/complimentary.py`
- Modify: `src/qwenpaw/app/billing/coordinator.py`
- Modify: `src/qwenpaw/app/billing/open_api.py`
- Modify: `src/qwenpaw/app/billing/usage.py`
- Test: `tests/unit/app/billing/test_billing_coordinator.py`
- Test: `tests/unit/app/billing/test_open_api_billing.py`
- Test: `tests/integration/test_open_api_billing_flow.py`

**Interfaces:**
- Produces: all coordinators use the requested/configured enforced billing mode without payer-name exceptions.
- Produces: missing effective catalog raises `CatalogNotReadyError` for every payer.
- Consumes: wallet overdraft policy only when a real priced hold exceeds funded credits.

- [ ] **Step 1: Replace complimentary tests with failing uniform-billing tests**

For a flagged user with zero funded balance and a published catalog, assert both client and OpenAPI sessions remain enforced, the provider executes, the model item captures its nonzero quote, and the wallet ends with equivalent debt:

```python
assert session.mode == "enforced"
assert settled.captured_credits == 1
assert balance.available == -1
assert balance.debt == 1
assert actual_usage_debit == 1
```

Also assert a flagged user with no published catalog receives `CatalogNotReadyError` and the supplier is not invoked.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/app/billing/test_billing_coordinator.py tests/unit/app/billing/test_open_api_billing.py tests/integration/test_open_api_billing_flow.py -q`

Expected: FAIL because the current username path switches to observe or an internal zero-price catalog.

- [ ] **Step 3: Remove runtime complimentary branches**

Delete imports and branches for `is_complimentary_user`, complimentary catalog creation, `complimentary_reason`, `complimentary_unpriced`, and the zero-price quote. The only insufficient-balance exception is now implemented by the wallet repository's database capability.

- [ ] **Step 4: Prove no runtime hard coding remains**

Run:

```bash
rg -n "szzz_admin|complimentary" src/qwenpaw/app/billing
```

Expected: no matches. The one permitted username match remains only in the Task 1 migration.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/unit/app/billing/test_billing_coordinator.py tests/unit/app/billing/test_open_api_billing.py tests/integration/test_open_api_billing_flow.py -q`

Expected: PASS.

```bash
git add src/qwenpaw/app/billing tests/unit/app/billing \
  tests/integration/test_open_api_billing_flow.py
git commit -m "refactor: remove complimentary billing bypass"
```

### Task 6: Verify every entry point and customer report uses real charges

**Files:**
- Modify: `src/qwenpaw/app/billing/reporting.py`
- Modify: `src/qwenpaw/app/routers/billing.py`
- Test: `tests/unit/app/billing/test_billing_reporting.py`
- Test: `tests/integration/test_console_billing_flow.py`
- Test: `tests/integration/test_open_api_billing_flow.py`
- Test: `tests/integration/test_expert_team_billing_flow.py`
- Test: `tests/integration/test_background_channel_billing.py`
- Test: `tests/unit/routers/test_aigc_studio.py`

**Interfaces:**
- Produces: usage reports count debt-backed `usage_capture` entries in `actual_debited_credits`.
- Produces: wallet APIs return signed balance and explicit debt projections.
- Preserves: source filters and existing item-level provider/model/token/credit details.

- [ ] **Step 1: Write failing report and entry-point tests**

Create a flagged payer with zero funded balance through each available real test harness. Assert the call reaches its fake supplier, captures the configured literal credits, and appears in the user's report with:

```python
assert order["actual_debited_credits"] == expected_credits
assert order["captured_credits"] == expected_credits
assert order["items"][0]["provider"] == expected_provider
assert order["items"][0]["model"] == expected_model
assert wallet["available"] == -expected_total
assert wallet["debt"] == expected_total
```

Keep ordinary zero-balance fixtures and assert they still stop before supplier execution.

- [ ] **Step 2: Run the cross-entry tests and verify RED**

Run:

```bash
pytest tests/unit/app/billing/test_billing_reporting.py \
  tests/integration/test_console_billing_flow.py \
  tests/integration/test_open_api_billing_flow.py \
  tests/integration/test_expert_team_billing_flow.py \
  tests/integration/test_background_channel_billing.py \
  tests/unit/routers/test_aigc_studio.py -q
```

Expected: at least the debt-backed actual debit/report assertions fail.

- [ ] **Step 3: Update reporting and route serialization**

Ensure actual debit aggregation uses the complete negative capture ledger delta rather than funded allocations. Pass the expanded wallet serializer through wallet, top-up, and admin inspection responses without exposing the capability flag.

- [ ] **Step 4: Run cross-entry tests and commit**

Run the Step 2 command.

Expected: PASS.

```bash
git add src/qwenpaw/app/billing/reporting.py \
  src/qwenpaw/app/routers/billing.py \
  tests/unit/app/billing/test_billing_reporting.py \
  tests/integration/test_console_billing_flow.py \
  tests/integration/test_open_api_billing_flow.py \
  tests/integration/test_expert_team_billing_flow.py \
  tests/integration/test_background_channel_billing.py \
  tests/unit/routers/test_aigc_studio.py
git commit -m "test: verify overdraft billing across entry points"
```

### Task 7: Full regression, migration audit, and cleanup

**Files:**
- Modify only files required by failures discovered in this task.
- Test: `tests/unit/app/billing/`
- Test: `tests/unit/app/storage/`
- Test: `tests/integration/`

**Interfaces:**
- Produces: a release-ready server commit with no complimentary runtime path and no public mutation surface for the overdraft flag.

- [ ] **Step 1: Run static searches for forbidden exposure and bypasses**

Run:

```bash
rg -n "szzz_admin|complimentary" src/qwenpaw/app --glob '!storage/schema.py' --glob '!db.py'
rg -n "billing_overdraft_enabled" src/qwenpaw/app/routers
```

Expected: the first command has no runtime billing matches; the second has no API DTO, request body, or client form matches.

- [ ] **Step 2: Run the complete billing/storage suite**

Run:

```bash
pytest tests/unit/app/billing tests/unit/app/storage \
  tests/unit/app/routers/test_billing.py \
  tests/unit/routers/test_aigc_studio.py \
  tests/integration/test_billing_repo_postgres.py \
  tests/integration/test_billing_schema_postgres.py \
  tests/integration/test_console_billing_flow.py \
  tests/integration/test_open_api_billing_flow.py \
  tests/integration/test_open_api_billing_postgres.py \
  tests/integration/test_expert_team_billing_flow.py \
  tests/integration/test_background_channel_billing.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint and diff validation**

Run:

```bash
ruff check src/qwenpaw/app/billing src/qwenpaw/app/storage \
  tests/unit/app/billing tests/unit/app/storage tests/integration
git diff --check
```

Expected: PASS with no formatting errors or whitespace defects.

- [ ] **Step 4: Review the migration against a copied production-like schema**

Start from a database containing the legacy user and wallet tables, run bootstrap twice, and query literal results:

```sql
SELECT username, billing_overdraft_enabled
FROM users
WHERE username = 'szzz_admin';

SELECT available_credits, debt_credits, held_overdraft_credits
FROM billing_wallets;
```

Expected: the existing admin flag is true; all existing wallet debt projections are zero; the second bootstrap changes no values.

- [ ] **Step 5: Commit any verification-only fixes**

If Step 1-4 required changes, stage only those files and commit:

```bash
git commit -m "fix: close overdraft billing regressions"
```

If no changes were required, do not create an empty commit.
