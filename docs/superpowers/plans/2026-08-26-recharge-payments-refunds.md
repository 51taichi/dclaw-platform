# Recharge Payments and Refunds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fixed recharge products, dynamic WeChat Pay/Alipay QR checkout, verified idempotent credit grants, and principal-safe refunds.

**Architecture:** Payment adapters only create/query/refund channel orders and verify callbacks. A payment service owns durable order state and calls the wallet service exactly once. Secrets use existing secret storage; callbacks are public but cryptographically verified.

**Tech Stack:** FastAPI, httpx, cryptography, PostgreSQL, existing secret directory, segno QR rendering in the frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-credit-wallet-billing-design.md`

## Global Constraints

- Requires the accounting foundation plan.
- QR codes are per-order dynamic codes, never uploaded static collection codes.
- Payment amount and granted credits come from a server-side product snapshot.
- Purchased credits never expire; bonus credits expire after 90 days.
- Duplicate callbacks, queries, and retries grant once.
- Refunds return to the original payment route and never exceed unused principal.

---

### Task 1: Recharge product and payment order persistence

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Create: `src/qwenpaw/app/storage/repos/payment_repo.py`
- Create: `src/qwenpaw/app/billing/payments/models.py`
- Test: `tests/unit/app/storage/repos/test_payment_repo.py`

**Interfaces:**
- Tables: `billing_recharge_products`, `billing_payment_orders`, `billing_refunds`, `billing_payment_events`.
- Produces immutable `RechargeProductSnapshot` and order state transitions.

- [ ] Write failing tests for the five confirmed products, immutable snapshots, unique merchant order number, legal state transitions, and duplicate event IDs.
- [ ] Run `pytest tests/unit/app/storage/repos/test_payment_repo.py -q`.
- [ ] Implement schema/repository with integer fen and credits; seed products through an idempotent application migration command.
- [ ] Run the focused test and `pytest tests/unit/app/storage -q`.
- [ ] Commit with message `feat: add recharge payment persistence`.

### Task 2: WeChat Pay and Alipay adapters

**Files:**
- Create: `src/qwenpaw/app/billing/payments/base.py`
- Create: `src/qwenpaw/app/billing/payments/wechat.py`
- Create: `src/qwenpaw/app/billing/payments/alipay.py`
- Test: `tests/unit/app/billing/payments/test_wechat.py`
- Test: `tests/unit/app/billing/payments/test_alipay.py`

**Interfaces:**
- `PaymentAdapter.create_qr(order) -> PaymentQr(code_url, expires_at, channel_order_id)`.
- `query_order`, `verify_callback`, and `refund` return normalized signed results.

- [ ] Write fixture-based failing tests for request signatures, response/callback verification, wrong merchant/amount rejection, QR expiry, query normalization, and refund idempotency.
- [ ] Run `pytest tests/unit/app/billing/payments -q`.
- [ ] Implement adapters using official API contracts; inject clock and HTTP client; never log keys or decrypted callback bodies.
- [ ] Run focused tests with network disabled.
- [ ] Commit with message `feat: add WeChat and Alipay payment adapters`.

### Task 3: Checkout, callback, query recovery, and credit grant

**Files:**
- Create: `src/qwenpaw/app/billing/payments/service.py`
- Create: `src/qwenpaw/app/routers/payments.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/routers/test_payments.py`

**Interfaces:**
- User endpoints list products, create checkout, query own order, and regenerate an expired QR safely.
- Public callback endpoints are channel-specific and unauthenticated at HTTP level but signature-required.

- [ ] Write failing API tests for user isolation, server-side amount authority, one-time grant, callback loss recovered by query, invalid callback no-op, and two payable replacement orders not double-crediting one purchase intent.
- [ ] Run `pytest tests/unit/app/routers/test_payments.py -q`.
- [ ] Implement payment orchestration and atomic `paid -> credits granted` transaction/outbox boundary.
- [ ] Run focused tests plus billing repository tests.
- [ ] Commit with message `feat: add QR recharge checkout`.

### Task 4: Refund calculation and channel execution

**Files:**
- Create: `src/qwenpaw/app/billing/refunds.py`
- Extend: `src/qwenpaw/app/routers/payments.py`
- Test: `tests/unit/app/billing/test_refunds.py`

**Interfaces:**
- Produces `RefundQuote(refundable_fen, purchased_credits_removed, promotional_credits_removed, reason)`.
- Supports full unused refund within seven days and partial unused-principal refund after usage.

- [ ] Write failing tests for full unused refund, consumed bonus reducing refundable principal, used purchased credits excluded, original-route enforcement, invoice-blocked status, concurrent refund requests, and maximum-principal invariant.
- [ ] Run `pytest tests/unit/app/billing/test_refunds.py -q`.
- [ ] Implement quote/freeze/submit/complete/fail states with compensating ledger entries on channel failure.
- [ ] Run `pytest tests/unit/app/billing/test_refunds.py tests/unit/app/routers/test_payments.py -q`.
- [ ] Commit with message `feat: add unused credit refunds`.

### Task 5: Payment configuration and operational checks

**Files:**
- Create: `src/qwenpaw/app/billing/payments/config.py`
- Create: `src/qwenpaw/app/routers/payment_settings.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/routers/test_payment_settings.py`

**Interfaces:**
- Admin API returns masked status and supports save/test; secrets persist under `SECRET_DIR`.

- [ ] Write failing tests proving secrets are encrypted/permission-restricted, never returned, test calls use injected clients, and only admins can change configuration.
- [ ] Run `pytest tests/unit/app/routers/test_payment_settings.py -q`.
- [ ] Implement config and health checks following the existing object-storage settings pattern.
- [ ] Run focused tests and `pytest tests/unit/routers/test_object_storage.py -q`.
- [ ] Commit with message `feat: add payment channel settings`.
