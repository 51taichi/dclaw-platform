# OpenAPI Credit Billing Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect each OpenAPI invocation and its model calls to the bound runtime user's personal credit wallet with reservation, evidence-gated settlement, durable details, and customer/admin APIs.

**Architecture:** An OpenAPI billing coordinator atomically creates one invocation and one usage order, then installs an immutable `ContextVar` inherited by nested model calls. Each model call reserves incrementally, persists one idempotent item, and settles independently; asynchronous token logging remains analytics-only.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, SQLAlchemy Core 2.x, PostgreSQL/SQLite, pytest, AgentScope model wrappers.

**Spec:** `docs/superpowers/specs/2026-08-28-open-api-credit-billing-design.md`

## Global Constraints

- Charge only the personal wallet resolved from `open_api_publications.bound_user_id`.
- Never accept client wallet IDs, owners, prices, credits, or supplier-commercial selectors.
- DClaw's published retail catalog is the only customer-price authority.
- Support `off|shadow|observe|enforced`; default to `shadow`.
- Billable captures actual retail credits, not-billable releases, unknown reconciles.
- Financial items are synchronous and durable; `token_usage_logs` is analytics only.
- Never overdraft or call a supplier after credit becomes insufficient.
- Never back-charge historical token logs or store prompts, responses, key plaintext, or supplier secrets.
- PostgreSQL is authoritative; SQLite remains supported by repository tests.
- The server API is implemented first; the client credit-center UI gets a companion plan after the contracts pass.

---

### Task 1: Durable invocation and item accounting schema

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/open_api/models.py`
- Test: `tests/unit/app/storage/test_billing_schema.py`
- Test: `tests/unit/app/storage/test_open_api_schema.py`

**Interfaces:**
- Consumes: existing `open_api_invocations`, `billing_usage_orders`, `billing_usage_items`, `create_all(engine)`.
- Produces: invocation-order links, order source/budget fields, and item idempotency/billability/price fields.

- [ ] **Step 1: Write failing fresh-schema and upgrade tests**

```python
def test_open_api_billing_columns_exist(engine):
    create_all(engine)
    inv = {c["name"] for c in inspect(engine).get_columns("open_api_invocations")}
    items = {c["name"] for c in inspect(engine).get_columns("billing_usage_items")}
    assert {"billing_usage_order_id", "billing_status", "quoted_credits",
            "captured_credits", "released_credits", "billing_error_code"} <= inv
    assert {"item_key", "billability", "quoted_credits",
            "price_snapshot_json", "started_at", "finished_at"} <= items
```

Also build a pre-bridge schema fixture, run `create_all()` twice, and assert the upgrade is idempotent.

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/unit/app/storage/test_billing_schema.py tests/unit/app/storage/test_open_api_schema.py -q`

Expected: FAIL because the links, totals, source, budget, and item keys are absent.

- [ ] **Step 3: Implement schema and migrations**

Add invocation billing totals/status; order `source_type`, `source_id`, `budget_credits`, and `reconciling_credits`; item `item_key`, `billability`, `quoted_credits`, `price_snapshot_json`, `started_at`, and `finished_at`. Add unique `(source_type, source_id)` and `(usage_order_id, item_key)` indexes. Implement idempotent SQLite/PostgreSQL upgrades without altering historical ledger or token rows.

- [ ] **Step 4: Run green and commit**

```bash
.venv/bin/python -m pytest tests/unit/app/storage/test_billing_schema.py tests/unit/app/storage/test_open_api_schema.py -q
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/open_api/models.py tests/unit/app/storage/test_billing_schema.py tests/unit/app/storage/test_open_api_schema.py
git commit -m "feat: link OpenAPI invocations to billing records"
```

### Task 2: Atomic invocation idempotency and billing context

**Files:**
- Modify: `src/qwenpaw/app/storage/repos/open_api_repo.py`
- Create: `src/qwenpaw/app/billing/open_api.py`
- Modify: `src/qwenpaw/app/agent_context.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Test: `tests/unit/app/billing/test_open_api_billing.py`
- Test: `tests/unit/app/open_api/test_billing_context.py`

**Interfaces:**
- Consumes: `BillingRepository`, `PriceCatalogService`, Task 1 keys.
- Produces: `OpenApiBillingCoordinator.begin_invocation`, `OpenApiBillingSession`, and async-safe billing-context accessors.

- [ ] **Step 1: Write failing ownership, idempotency, rollback, and isolation tests**

```python
def test_begin_uses_bound_user_wallet(coordinator):
    session = coordinator.begin_invocation(command(bound_user_id="24"))
    assert session.bound_user_id == "24"
    assert session.wallet_id == wallet_for("24")["id"]

def test_same_key_different_payload_conflicts(coordinator):
    coordinator.begin_invocation(command(key="req-1", message="first"))
    with pytest.raises(IdempotencyConflictError):
        coordinator.begin_invocation(command(key="req-1", message="changed"))
```

Prove same-key/same-payload replay returns the existing pair, app/publication namespaces do not collide, an injected failure between order and invocation writes rolls back both, concurrent async contexts remain isolated, and cleanup prevents leakage.

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_open_api_billing.py tests/unit/app/open_api/test_billing_context.py -q`

Expected: FAIL because the coordinator and billing `ContextVar` do not exist.

- [ ] **Step 3: Implement atomic coordinator and immutable context**

```python
@dataclass(frozen=True)
class OpenApiBillingSession:
    invocation_id: str
    usage_order_id: str
    wallet_id: str
    bound_user_id: str
    app_id: str
    api_key_id: str
    publication_id: str
    catalog_version: str
    mode: str
```

Canonicalize strict JSON and hash the request. Namespace the optional client key as `openapi:{app_id}:{publication_id}:{key}`. Create/recover invocation and order in one transaction. Add `set/get/reset_current_billing_context`; install only after commit and reset in `finally`.

- [ ] **Step 4: Run green and commit**

```bash
.venv/bin/python -m pytest tests/unit/app/billing/test_open_api_billing.py tests/unit/app/open_api/test_billing_context.py tests/unit/app/storage/repos/test_open_api_repo.py -q
git add src/qwenpaw/app/storage/repos/open_api_repo.py src/qwenpaw/app/billing/open_api.py src/qwenpaw/app/agent_context.py src/qwenpaw/app/open_api/runtime.py tests/unit/app/billing/test_open_api_billing.py tests/unit/app/open_api/test_billing_context.py
git commit -m "feat: create OpenAPI billing sessions"
```

### Task 3: Incremental reservation and per-item evidence settlement

**Files:**
- Modify: `src/qwenpaw/app/billing/usage.py`
- Modify: `src/qwenpaw/app/billing/open_api.py`
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Test: `tests/unit/app/billing/test_open_api_billing.py`
- Test: `tests/unit/app/storage/repos/test_billing_repo.py`
- Test: `tests/integration/test_open_api_billing_postgres.py`

**Interfaces:**
- Consumes: `QuoteRequest`, locked catalog version, exact lot hold/capture/release.
- Produces: `reserve_model_call(command) -> ReservedUsageItem` and `settle_model_call(command) -> UsageItemResult`.

- [ ] **Step 1: Write failing multi-call and mixed-billability tests**

```python
def test_three_calls_share_order_and_hold_incrementally(service):
    one = service.reserve_model_call(reserve("call-1", max_output_tokens=1000))
    two = service.reserve_model_call(reserve("call-2", max_output_tokens=2000))
    assert one.usage_order_id == two.usage_order_id
    assert len(service.list_items(one.usage_order_id)) == 2

def test_insufficient_increment_stops_before_supplier(service, supplier):
    service.reserve_model_call(reserve("call-1", credits=80))
    with pytest.raises(InsufficientUsageCreditsError):
        service.reserve_model_call(reserve("call-2", credits=30))
    assert supplier.calls == []
```

Add billable/not-billable/unknown mixtures, partial capture, unused release, item replay/conflict, expiry, trial restrictions, invocation budget, and capture-vs-release concurrency.

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_open_api_billing.py tests/unit/app/storage/repos/test_billing_repo.py -q`

- [ ] **Step 3: Implement item commands and aggregate projections**

```python
@dataclass(frozen=True)
class SettleModelCall:
    usage_order_id: str
    item_key: str
    supplier_reference: str
    billability: Literal["billable", "not_billable", "unknown"]
    evidence: Mapping[str, JSONValue]
    actual_input_tokens: int
    actual_output_tokens: int
```

Lock order/wallet, quote each item with the invocation catalog, and append holds atomically. Capture actual retail usage, release excess, or retain only unknown credit. Derive order/invocation totals from durable items and ledger allocations.

- [ ] **Step 4: Verify SQLite/PostgreSQL and commit**

```bash
.venv/bin/python -m pytest tests/unit/app/billing/test_open_api_billing.py tests/unit/app/storage/repos/test_billing_repo.py tests/integration/test_open_api_billing_postgres.py -q
git add src/qwenpaw/app/billing/usage.py src/qwenpaw/app/billing/open_api.py src/qwenpaw/app/storage/repos/billing_repo.py tests/unit/app/billing/test_open_api_billing.py tests/unit/app/storage/repos/test_billing_repo.py tests/integration/test_open_api_billing_postgres.py
git commit -m "feat: settle OpenAPI model calls by evidence"
```

### Task 4: Model wrapper financial meter

**Files:**
- Create: `src/qwenpaw/app/billing/model_meter.py`
- Modify: `src/qwenpaw/token_usage/model_wrapper.py`
- Modify: `src/qwenpaw/agents/model_factory.py`
- Test: `tests/unit/app/billing/test_model_meter.py`
- Test: `tests/unit/token_usage/test_token_usage.py`

**Interfaces:**
- Consumes: Task 2 context and Task 3 reservation/settlement.
- Produces: `BillingModelMeter.before_call`, `record_response`, and `record_exception`.

- [ ] **Step 1: Write failing response, streaming, timeout, and queue-loss tests**

```python
async def test_financial_item_is_durable_before_analytics(wrapper, sink):
    await consume(wrapper(messages=[{"role": "user", "content": "hi"}]))
    assert sink.financial[0].billability == "billable"
    assert sink.analytics[0].prompt_tokens == 12

async def test_ambiguous_timeout_is_unknown(wrapper, sink):
    with pytest.raises(TimeoutError):
        await consume(wrapper(messages=[]))
    assert sink.financial[0].billability == "unknown"
```

Prove local preflight failure is not-billable, success without official usage is unknown, streaming settles once, a rejected analytics event does not lose billing, and non-OpenAPI calls remain analytics-only.

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_model_meter.py tests/unit/token_usage/test_token_usage.py -q`

- [ ] **Step 3: Implement meter and minimized evidence adapters**

Reserve before provider execution; synchronously persist the financial outcome before enqueueing `_UsageEvent`. Evidence may contain supplier reference, official usage, response class/status, adapter version, and timestamps, never prompt/response content or secrets. A billing-write failure after supplier contact forces reconciling.

- [ ] **Step 4: Run green and commit**

```bash
.venv/bin/python -m pytest tests/unit/app/billing/test_model_meter.py tests/unit/token_usage/test_token_usage.py -q
git add src/qwenpaw/app/billing/model_meter.py src/qwenpaw/token_usage/model_wrapper.py src/qwenpaw/agents/model_factory.py tests/unit/app/billing/test_model_meter.py tests/unit/token_usage/test_token_usage.py
git commit -m "feat: meter OpenAPI model calls for billing"
```

### Task 5: OpenAPI preflight, SSE billing events, and recovery

**Files:**
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `src/qwenpaw/app/storage/repos/open_api_repo.py`
- Test: `tests/unit/app/test_open_api_router.py`
- Test: `tests/integration/test_open_api_billing_flow.py`

**Interfaces:**
- Consumes: Tasks 2-4.
- Produces: `Idempotency-Key`, `X-DClaw-Invocation-Id`, `X-DClaw-Billing-Status`, terminal billing SSE events, and restart recovery.

- [ ] **Step 1: Write failing end-to-end router tests**

```python
def test_initial_insufficient_balance_never_calls_supplier(client, supplier):
    response = client.post(open_url, headers=key_headers, json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "insufficient_credits"
    assert supplier.calls == []

def test_expert_team_finishes_one_order_with_three_items(client):
    events = read_sse(client, expert_team_payload)
    assert events[-1]["type"] == "billing.completed"
    assert item_count(events[-1]["invocation_id"]) == 3
```

Cover replay/conflict, partial completion, disconnect, unknown evidence, missing catalog, shadow/observe no mutation, process restart, and `open_api_invocations.token_summary` aggregation from all durable items.

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/unit/app/test_open_api_router.py tests/integration/test_open_api_billing_flow.py -q`

- [ ] **Step 3: Integrate preflight and streaming finalization**

Authenticate, canonicalize, begin/recover billing, install context, then start the agent. Map `idempotency_conflict`, `insufficient_credits`, and `catalog_not_ready` before streaming when applicable. Emit sealed `billing.completed` or `billing.interrupted` events without evidence leakage. Finalization continues after client disconnect and rebuilds `open_api_invocations.token_summary` from durable usage items rather than the asynchronous analytics queue.

- [ ] **Step 4: Implement idempotent startup recovery**

Scan nonterminal OpenAPI orders. Recover deterministic durable outcomes; otherwise mark only unresolved items/order reconciling. Repeated recovery must make no additional ledger change.

- [ ] **Step 5: Run green and commit**

```bash
.venv/bin/python -m pytest tests/unit/app/test_open_api_router.py tests/integration/test_open_api_billing_flow.py -q
git add src/qwenpaw/app/routers/open_api.py src/qwenpaw/app/open_api/runtime.py src/qwenpaw/app/storage/repos/open_api_repo.py tests/unit/app/test_open_api_router.py tests/integration/test_open_api_billing_flow.py
git commit -m "feat: enforce OpenAPI credit billing flow"
```

### Task 6: Customer/admin reporting, reconciliation, and rollout gate

**Files:**
- Modify: `src/qwenpaw/app/routers/billing.py`
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Create: `src/qwenpaw/app/billing/reporting.py`
- Create: `docs/operations/open-api-billing-rollout.md`
- Test: `tests/unit/app/routers/test_billing.py`
- Test: `tests/unit/app/billing/test_billing_reporting.py`

**Interfaces:**
- Consumes: durable invocation/order/items.
- Produces: user list/detail/summary, admin filtering/reconciliation, rollout modes, and durable `billing_cutover_at`.

- [ ] **Step 1: Write failing isolation, filtering, and redaction tests**

```python
def test_user_expands_own_order(client, own_order):
    response = client.get(f"/api/user/billing/usage-orders/{own_order.id}")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3

def test_user_cannot_read_other_order(client, other_order):
    assert client.get(f"/api/user/billing/usage-orders/{other_order.id}").status_code == 404
```

Test date/model/publication/app/status filters, admin visibility, evidence/cost redaction, shadow estimates, manual-resolution audit, and historical-token exclusion.

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/unit/app/routers/test_billing.py tests/unit/app/billing/test_billing_reporting.py -q`

- [ ] **Step 3: Implement APIs and rollout controls**

```text
GET /api/user/billing/usage-orders
GET /api/user/billing/usage-orders/{order_id}
GET /api/user/billing/open-api-summary
GET /api/admin/billing/usage-orders
GET /api/admin/billing/reconciliation
POST /api/admin/billing/reconciliation/{item_id}/resolve
```

Manual resolution requires actor/reason and immutable audit. Persist `billing_cutover_at` only on explicit enforced activation. Observe calculates reservation failures without wallet mutation. Return low-balance/top-up metadata but do not implement payment collection.

- [ ] **Step 4: Run full server verification**

```bash
.venv/bin/python -m pytest tests/unit/app/billing tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/storage/repos/test_open_api_repo.py tests/unit/app/routers/test_billing.py tests/unit/app/test_open_api_router.py tests/integration/test_open_api_billing_flow.py tests/integration/test_open_api_billing_postgres.py -q
```

Live PostgreSQL is mandatory before enforced deployment. Run Python hooks, `compileall`, `git diff --check`, a fresh migration, and an upgrade from a production schema snapshot.

- [ ] **Step 5: Write rollout/rollback runbook and commit**

Document catalog readiness, wallet seeding, shadow comparison, observe thresholds, reconciliation alerts, cutover, enforced activation, container/Nginx rollback, and database-restore implications.

```bash
git add src/qwenpaw/app/routers/billing.py src/qwenpaw/app/storage/repos/billing_repo.py src/qwenpaw/app/billing/reporting.py tests/unit/app/routers/test_billing.py tests/unit/app/billing/test_billing_reporting.py docs/operations/open-api-billing-rollout.md
git commit -m "feat: expose OpenAPI credit consumption details"
```
