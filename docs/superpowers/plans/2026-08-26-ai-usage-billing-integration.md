# AI Usage Billing Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect text calls, AIGC jobs, and composite workflows to shadow/enforced usage orders using supplier billability as the settlement trigger and locked DClaw retail prices as the debit amount.

**Architecture:** Provider adapters normalize supplier evidence. Text model usage creates child usage items from recorded tokens; AIGC jobs retain durable usage-order IDs; workflows either sum children or capture a fixed parent quote. Unknown supplier states enter reconciliation.

**Tech Stack:** Existing provider wrappers, FastAPI, asyncio workers, PostgreSQL billing services, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-credit-wallet-billing-design.md`

## Global Constraints

- Requires completion of `2026-08-26-credit-accounting-foundation.md`.
- Supplier activity decides billable versus non-billable; DClaw catalog decides credits.
- Supplier discounts never alter customer debit.
- Automatic retries cannot duplicate customer settlement.
- Unknown supplier state is neither captured nor released.

---

### Task 1: Supplier evidence contract

**Files:**
- Create: `src/qwenpaw/app/billing/evidence.py`
- Modify: `src/qwenpaw/providers/provider.py`
- Test: `tests/unit/app/billing/test_evidence.py`

**Interfaces:**
- Produces `SupplierEvidence(provider_id, model_key, request_id, billability, quantities, status, error_code, checked_at)`.
- `billability` is `billable|not_billable|unknown`.

- [ ] Write failing normalization tests for token usage, successful async generation, explicit no-charge failure, and timeout/unknown.
- [ ] Run `pytest tests/unit/app/billing/test_evidence.py -q`; expect import failure.
- [ ] Implement the evidence type and provider hook `billing_evidence(result_or_error) -> SupplierEvidence` with a safe unknown default.
- [ ] Run `pytest tests/unit/app/billing/test_evidence.py tests/contract/providers -q`.
- [ ] Commit with `git commit -am "feat: normalize supplier billing evidence"` after staging the new files.

### Task 2: Text-model settlement

**Files:**
- Modify: `src/qwenpaw/token_usage/model_wrapper.py`
- Modify: `src/qwenpaw/token_usage/manager.py`
- Modify: `src/qwenpaw/app/storage/schema.py`
- Test: `tests/unit/token_usage/test_billing_integration.py`

**Interfaces:**
- Extends token usage with `provider_id`, stable `model_key`, `usage_order_id`, and supplier request ID.
- Calls `UsageService.settle_text_item(order_id, evidence, input_tokens, output_tokens)`.

- [ ] Write failing tests proving actual input/output tokens select the locked rates, a multi-call agent produces child items, shadow mode does not debit, enforced mode pauses before an unaffordable next call, and duplicate usage callbacks settle once.
- [ ] Run `pytest tests/unit/token_usage/test_billing_integration.py -q`.
- [ ] Implement context propagation and settlement after usage is recorded; preserve existing token-usage analytics.
- [ ] Run `pytest tests/unit/token_usage tests/unit/app/storage/repos/test_token_usage_repo.py -q`.
- [ ] Commit with message `feat: settle text model credits`.

### Task 3: AIGC quote, hold, and settlement

**Files:**
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`
- Test: `tests/unit/routers/test_aigc_billing.py`

**Interfaces:**
- Job creation accepts a server-generated quote reference, never a client price.
- `AigcJob` persists `usage_order_id` and `price_snapshot`.
- Job completion passes normalized supplier evidence to `UsageService`.

- [ ] Write failing tests for image/video parameter quotes, full holds, billable failure capture, non-billable failure release, unknown reconciliation, restart recovery, and retry idempotency.
- [ ] Run `pytest tests/unit/routers/test_aigc_billing.py -q`.
- [ ] Implement minimal hooks around existing job creation/run completion without moving generation logic into the billing package.
- [ ] Run `pytest tests/unit/routers/test_aigc_billing.py tests/unit/routers/test_aigc_studio.py -q`.
- [ ] Commit with message `feat: bill AIGC jobs with locked quotes`.

### Task 4: Workflow parent/child billing

**Files:**
- Create: `src/qwenpaw/app/billing/workflows.py`
- Modify: `src/qwenpaw/app/expert_teams.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`
- Test: `tests/unit/app/billing/test_workflow_billing.py`

**Interfaces:**
- Produces `WorkflowBillingPolicy(mode="component_sum"|"fixed", fixed_rule_id=None, partial_failure_policy=...)`.
- Produces parent order with child usage item references.

- [ ] Write failing tests for component-sum totals, fixed-price single capture, component cost retention, publication rejection without partial-failure policy, and resume after insufficient balance.
- [ ] Run `pytest tests/unit/app/billing/test_workflow_billing.py -q`.
- [ ] Implement workflow coordinator and attach it to expert-team and AIGC script workflows.
- [ ] Run the focused test plus `pytest tests/unit/app/test_expert_teams.py tests/unit/routers/test_aigc_studio.py -q`.
- [ ] Commit with message `feat: add workflow credit settlement`.

### Task 5: Reconciliation worker and shadow report

**Files:**
- Create: `src/qwenpaw/app/billing/reconciliation.py`
- Create: `src/qwenpaw/app/routers/billing_reconciliation.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/billing/test_reconciliation.py`

**Interfaces:**
- Worker `reconcile_due_orders(limit: int) -> ReconciliationSummary`.
- Admin endpoints list stuck orders and resolve with `billable|not_billable` plus mandatory reason.

- [ ] Write failing tests for bounded backoff, process restart, admin reason/audit requirements, and no customer mutation in shadow mode.
- [ ] Run `pytest tests/unit/app/billing/test_reconciliation.py -q`.
- [ ] Implement the worker and admin queue without holding DB transactions across supplier HTTP calls.
- [ ] Run `pytest tests/unit/app/billing/test_reconciliation.py tests/unit/app/billing -q`.
- [ ] Commit with message `feat: reconcile uncertain AI charges`.
