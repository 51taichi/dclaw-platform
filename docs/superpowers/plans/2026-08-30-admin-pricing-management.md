# Admin Pricing Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the protected RMB pricing console defined by the approved spec and eliminate `catalog_not_ready` after first publication.

**Architecture:** Append-only trusted costs and policies generate reviewed immutable catalogs through the existing pricing engine. Runtime keeps locking a published catalog while freshness is advisory. A separate React console uses typed APIs and an in-memory 15-minute billing unlock.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy Core, PostgreSQL/SQLite, pytest, openpyxl, React, TypeScript, Ant Design, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-30-admin-pricing-management-design.md`

## Global Constraints

- UI/Excel/customer prices use RMB and credits only; original currency is internal audit evidence.
- Defaults: 100 credits/RMB, 5% risk buffer, 1.3 minimum multiplier.
- Precedence: model, category, provider, global; first configured value wins.
- Staleness never disables an existing sellable model; missing trusted cost blocks only new models.
- Auto-raise is capped at 20% and once/model/24h; decreases require review.
- Sensitive writes require password re-verification valid for 15 minutes.
- Excel import produces preview/draft only.
- Preserve unrelated dirty changes in both repositories.

---

### Task 1: Persistence Foundation

**Files:** Modify `src/qwenpaw/app/storage/schema.py`; create `src/qwenpaw/app/storage/repos/pricing_admin_repo.py`; test `tests/unit/app/storage/test_billing_schema.py` and `tests/unit/app/storage/repos/test_pricing_admin_repo.py`.

**Interfaces:** `append_cost_snapshot`, `latest_trusted_costs`, `replace_policy(expected_revision)`, `record_import`, `create_unlock`, `validate_unlock`, `append_audit`.

- [ ] Write failing idempotent-schema, append-only audit/cost, policy conflict, unlock expiry, and import-hash tests.

```python
def test_cost_history_is_append_only(repo):
    a = repo.append_cost_snapshot(cost("1.00", T0))
    b = repo.append_cost_snapshot(cost("1.20", T1))
    assert a != b
    assert repo.latest_trusted_costs()[0]["rmb_cost_decimal"] == "1.20"
```

- [ ] Run `uv run pytest tests/unit/app/storage/test_billing_schema.py tests/unit/app/storage/repos/test_pricing_admin_repo.py -q`; expect missing tables/repository failure.
- [ ] Add `billing_cost_snapshots`, `billing_pricing_policies`, `billing_pricing_imports`, `billing_pricing_unlocks`, `billing_pricing_audits`, catalog `revision`, constraints/indexes, hashed tokens, and immutable SQLite/PostgreSQL audit triggers.
- [ ] Re-run the tests plus `tests/integration/test_billing_schema_postgres.py`; expect PASS.
- [ ] Commit with `git commit -m "feat: persist pricing administration data"`.

### Task 2: Decimal Pricing and Model Inventory

**Files:** Create `billing/pricing_models.py`, `pricing_policy.py`, `pricing_inventory.py`; modify `providers/provider_manager.py`; create `test_pricing_policy.py` and `test_pricing_inventory.py`.

**Interfaces:** `resolve_multiplier`, `price_cost`, `build_catalog_rules`, `PricingModelInventory.list_enabled`.

- [ ] Write failing hierarchy, 5% buffer, 1.3 floor, ceiling-rounding, six-category, hidden-model, and dimension tests.

```python
result = price_cost(cost("0.0100"), Decimal("1.1"), DEFAULTS)
assert result.rmb_sale_price == Decimal("0.0136500")
assert result.credits == 2
```

- [ ] Run both new test files; expect missing-module failure.
- [ ] Implement immutable Decimal types, model/category/provider/global lookup, enabled local inventory without network discovery, and existing `PriceRule` generation with full cost/FX/multiplier/RMB snapshots.
- [ ] Run new tests plus `test_pricing.py` and `test_provider_manager.py`; expect PASS.
- [ ] Commit with `git commit -m "feat: derive RMB prices for enabled models"`.

### Task 3: Insurance Unlock and Admin Publication

**Files:** Create `billing/pricing_unlock.py`, `pricing_admin.py`; modify `routers/billing.py`, `price_catalog_repo.py`, `billing/pricing.py`; create unlock/admin tests and extend router tests.

**Interfaces:** unlock/status endpoints; overview/inventory/history reads; unlock-protected cost, policy, preview, publish, rollback commands using `X-Billing-Unlock`.

- [ ] Write failing tests for wrong password/rate limit/expiry/role, 423 without unlock, missing-cost blocker, optimistic conflict, audit, immutable publish, and clone-based rollback.

```python
response = client.post("/admin/billing/pricing/policies",
                       headers=admin_headers, json=POLICY)
assert response.status_code == 423
```

- [ ] Run the focused tests; expect missing service/routes failure.
- [ ] Verify current durable admin password, store only SHA-256 token hash, expire after 15 minutes, revoke on account/session changes, and audit IP/before/after/reason. Never mutate a historical catalog.
- [ ] Run focused tests, router tests, existing pricing tests, and login-rate-limit tests; expect PASS.
- [ ] Commit with `git commit -m "feat: protect and manage pricing publication"`.

### Task 4: Continuity, Sync, and Protection

**Files:** Create `billing/pricing_sync.py`; modify `billing/open_api.py` and `price_catalog_repo.py`; create sync tests and extend OpenAPI integration tests.

**Interfaces:** `PricingSourceAdapter.fetch`, `check_due_sources`, `freshness`, `apply_protection`, latest effective published catalog lock.

- [ ] Write failing tests proving stale metadata still reaches supplier, in-flight requests keep old catalog, API/aggregator/page/manual schedules are 1/7/7/30 days, and 20%/24h caps work.

```python
flow.publish_catalog(metadata={"source_stale": True})
assert flow.invoke().status_code != 503
assert flow.supplier_calls == 1
```

- [ ] Run sync and OpenAPI flow tests; expect failure.
- [ ] Implement candidate-only page sync, reviewed decreases, system-actor protection publication/audit/alerts, and runtime selection that ignores freshness but never selects draft/future/empty/zero-price catalogs.
- [ ] Run pricing, OpenAPI unit, and OpenAPI integration suites; expect PASS.
- [ ] Commit with `git commit -m "feat: keep pricing available and protect margins"`.

### Task 5: Reviewed Excel Workflow

**Files:** Modify `pyproject.toml`, `uv.lock`, `routers/billing.py`; create `billing/pricing_excel.py` and `test_pricing_excel.py`.

**Interfaces:** four RMB exports; import preview; unlock-protected confirm creating snapshots/policies/draft only.

- [ ] Add openpyxl and failing tests for unsafe floor, malformed/formula/macro/duplicate/oversized workbooks and content-hash idempotency.

```python
preview = service.preview_import(workbook(multiplier="1.1"), "p.xlsx", "1")
assert preview.rows[0].code == "below_safe_floor"
assert service.catalog_count() == 0
```

- [ ] Run Excel tests; expect missing module failure.
- [ ] Implement strict fixed-column parsing and current/trusted/template/risk exports; routine sheets must not contain foreign currency.
- [ ] Run Excel and router tests; expect PASS.
- [ ] Commit with `git commit -m "feat: add reviewed pricing Excel workflow"`.

### Task 6: Typed Client and RMB Views

**Files in `/Users/moxi/Desktop/codex space/dclaw-client`:** Modify billing API types/module/tests and `RemoteDataTabs.tsx`; create `PricingTab`, overview, models, rules, drafts, history, styles, and tests.

**Interfaces:** typed pricing API and five provider/category-grouped read views.

- [ ] Write failing API/render tests proving typed requests, grouping, dimensions, coverage/freshness, and no `USD`/`美元` in routine views.

```typescript
expect(await screen.findByText("百炼")).toBeInTheDocument();
expect(screen.getByText("¥0.0137")).toBeInTheDocument();
expect(screen.queryByText(/USD|美元/)).not.toBeInTheDocument();
```

- [ ] Run `npm --prefix console test -- PricingTab.test.tsx billing.test.ts --run`; expect failure against raw JSON UI.
- [ ] Implement typed calls and five tabs with initialization guidance and expandable dimension rows.
- [ ] Run billing UI/API tests and `npm --prefix console run typecheck`; expect PASS.
- [ ] Commit client changes with `git commit -m "feat: add RMB pricing management views"`.

### Task 7: Client Unlock and Mutations

**Files in client:** Create `PricingUnlockModal.tsx` and test; modify pricing components and billing API module.

**Interfaces:** memory-only token/countdown; guarded edit/import/publish/rollback.

- [ ] Write failing tests for password erasure, no local/session storage, 15-minute expiry, retained unsaved form, header scoping, and final publish/rollback confirmation.

```typescript
await unlockWithPassword("secret");
vi.advanceTimersByTime(15 * 60 * 1000);
expect(screen.getByRole("button", { name: "解锁计费设置" })).toBeEnabled();
```

- [ ] Run pricing client tests; expect missing UI failure.
- [ ] Implement memory-only `PricingUnlock`; send `X-Billing-Unlock` only on sensitive requests and require re-unlock after expiry.
- [ ] Run all billing UI/API tests and typecheck; expect PASS.
- [ ] Commit client changes with `git commit -m "feat: protect pricing administration workflows"`.

### Task 8: End-to-End Acceptance and Rollout

**Files:** Create `tests/integration/test_admin_pricing_flow.py`, `docs/operations/admin-pricing-rollout.md`; modify PostgreSQL OpenAPI billing integration test.

**Interfaces:** inventory -> verified RMB cost -> unlock -> preview -> publish -> OpenAPI Agent/supplier call -> locked settlement.

- [ ] Write the failing end-to-end test.

```python
token = unlock(admin, "admin-password")
seed_verified_rmb_costs(admin, token)
published = publish(admin, initialize_preview(admin), token)
assert published["status"] == "published"
assert open_api.post(INVOKE_URL, json=REQUEST).status_code != 503
assert supplier.call_count == 1
```

- [ ] Run it, complete dependency wiring, and document backup, dry-run, coverage blockers, first publication, SQL verification, replay, audit, alerts, and clone-based rollback.
- [ ] Run server gate: `uv run pytest tests/unit/app/billing tests/unit/app/routers/test_billing.py tests/unit/app/storage/test_billing_schema.py tests/integration/test_admin_pricing_flow.py tests/integration/test_open_api_billing_flow.py tests/integration/test_open_api_billing_postgres.py -q` and relevant Ruff checks.
- [ ] Run client gate: `npm --prefix '/Users/moxi/Desktop/codex space/dclaw-client/console' test -- src/pages/Settings/Billing src/api/modules/billing.test.ts --run` and typecheck.
- [ ] Commit acceptance assets, invoke `superpowers:requesting-code-review`, resolve findings via `superpowers:receiving-code-review`, rerun both gates, inspect both worktrees for secrets/unrelated changes/persisted unlocks, then offer verified commits for push.
