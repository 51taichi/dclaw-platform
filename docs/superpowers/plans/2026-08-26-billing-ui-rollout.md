# Billing UI and Production Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver customer wallet/recharge/usage screens, exact text/AIGC price visibility, administrator billing controls, production build synchronization, and staged enforcement.

**Architecture:** React pages in the adjacent `dclaw-client/console` repository consume server-owned quotes and accounting views. The UI never calculates authoritative money or credits. Rollout progresses from shadow reports to pilot enforcement and then general recharge.

**Tech Stack:** React 18, TypeScript 5.8, Ant Design, Vitest/Testing Library, Vite, DClaw FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-25-credit-wallet-billing-design.md`

## Global Constraints

- Requires the accounting, usage-integration, and payment plans.
- Frontend source is `../dclaw-client/console`; built assets are synchronized into `src/qwenpaw/console` through the existing build workflow.
- The client repository currently has unrelated dirty changes; execution must use an isolated worktree and preserve those changes.
- The backend is authoritative for price, balance, payment amount, expiry, and refund value.
- Expensive operations show an exact quote before submission.

---

### Task 1: Typed billing API client and shared balance UI

**Files:**
- Create: `../dclaw-client/console/src/api/modules/billing.ts`
- Create: `../dclaw-client/console/src/api/types/billing.ts`
- Modify: `../dclaw-client/console/src/api/index.ts`
- Modify: `../dclaw-client/console/src/api/types/index.ts`
- Create: `../dclaw-client/console/src/features/billing/BalanceBadge.tsx`
- Test: `../dclaw-client/console/src/features/billing/BalanceBadge.test.tsx`

**Interfaces:**
- Produces `billingApi.getWallet`, `listLedger`, `quote`, `listProducts`, `createCheckout`, `getPaymentOrder`, `requestRefund`.

- [ ] Write failing render/API tests for available/held display, low-balance state, loading, and 409 `insufficient_credits` handling.
- [ ] Run `npm test -- --run src/features/billing/BalanceBadge.test.tsx` from `../dclaw-client/console`.
- [ ] Implement typed contracts and a balance badge that refreshes after settlement events.
- [ ] Run the focused test and `npm run format:check`.
- [ ] Commit in the client worktree with message `feat: add billing client and balance badge`.

### Task 2: Customer wallet, recharge, QR, ledger, and refund pages

**Files:**
- Create: `../dclaw-client/console/src/pages/Wallet/index.tsx`
- Create: `../dclaw-client/console/src/pages/Wallet/index.module.less`
- Create: `../dclaw-client/console/src/pages/Wallet/WalletPage.test.tsx`
- Modify: `../dclaw-client/console/src/layouts/ClientLayout/index.tsx`
- Modify: `../dclaw-client/console/src/layouts/Sidebar.tsx`
- Test: `../dclaw-client/console/src/layouts/ClientLayout.test.tsx`

**Interfaces:**
- Renders separated purchased/promotional balances, expiries, five products, dynamic QR expiry/regeneration, order status, ledger filters, and refund quote.

- [ ] Write failing page tests for product breakdown, QR polling recovery, duplicate-click prevention, permanent versus 90-day bonus copy, refund confirmation, and original-route status.
- [ ] Run the Wallet page test.
- [ ] Implement the page using only server-returned amounts and states; do not generate or trust a client-side order amount.
- [ ] Run page tests, typecheck, lint, and accessibility-focused queries.
- [ ] Commit with message `feat: add customer credit wallet`.

### Task 3: Chat and AIGC quote/settlement presentation

**Files:**
- Modify: `../dclaw-client/console/src/pages/Chat/index.tsx`
- Modify: `../dclaw-client/console/src/pages/AigcStudio/canvasJobActions.ts`
- Modify: `../dclaw-client/console/src/pages/AigcStudio/components/ImageNode/ImageComposer.tsx`
- Modify: `../dclaw-client/console/src/pages/AigcStudio/components/VideoNode/VideoComposer.tsx`
- Modify: `../dclaw-client/console/src/pages/AigcStudio/components/AudioNode/AudioComposer.tsx`
- Test: `../dclaw-client/console/src/pages/Chat/ChatBilling.test.tsx`
- Test: `../dclaw-client/console/src/pages/AigcStudio/AigcBilling.test.tsx`

**Interfaces:**
- Chat displays final tokens/credits and task spending cap.
- AIGC requests a quote after billable parameters change and confirms exact credits before run.

- [ ] Write failing tests for model tier/exact model display, quote refresh on duration/resolution change, exact hold confirmation, insufficient-balance recharge link, final charge, released hold, and reconciling state.
- [ ] Run the focused Chat/AIGC tests.
- [ ] Implement price UI without duplicating rate tables in TypeScript.
- [ ] Run `npm exec -- vitest run` for all touched Chat/AIGC tests and `npm run build`.
- [ ] Commit with message `feat: show AI credit quotes and charges`.

### Task 4: Administrator billing console

**Files:**
- Create: `../dclaw-client/console/src/pages/Settings/Billing/index.tsx`
- Create: `../dclaw-client/console/src/pages/Settings/Billing/BillingSettings.test.tsx`
- Modify: `../dclaw-client/console/src/layouts/AdminLayout/index.tsx`
- Modify: `../dclaw-client/console/src/layouts/Sidebar.tsx`

**Interfaces:**
- Tabs: price catalogs, recharge products, payment channels, wallets/ledger, usage reconciliation, refunds, reports.

- [ ] Write failing tests for masked secrets, draft validation errors, catalog diff/publish confirmation, mandatory admin reasons, reconciliation resolution, and no direct balance-edit control.
- [ ] Run the focused settings test.
- [ ] Implement focused components; split each tab into its own file when it owns independent server state.
- [ ] Run settings tests, `npm run lint`, `npm run format:check`, and `npm run build`.
- [ ] Commit with message `feat: add billing administration console`.

### Task 5: Cross-repository build and acceptance suite

**Files:**
- Modify generated assets under `src/qwenpaw/console/` only through the established website build script.
- Create: `tests/e2e/test_billing_acceptance.py`
- Update: `docs/deployment-postgres-redis.md`

**Interfaces:**
- Produces a deployable server image with matching client API contracts.

- [ ] Write E2E tests for wallet creation, shadow quote, pilot debit, QR mocked payment, duplicate callback, AIGC billable/non-billable outcomes, refund, and ledger reconstruction.
- [ ] Run the E2E test against PostgreSQL and Redis; expect failures before asset synchronization/configuration.
- [ ] Run the existing client build/sync command documented by `scripts/website_build.sh`, then build the Docker image.
- [ ] Run backend unit suites, client targeted suites, `npm run build`, Docker health check, and the E2E acceptance test.
- [ ] Commit server assets/docs/tests with message `feat: ship credit billing console`.

### Task 6: Staged production activation

**Files:**
- Create: `docs/credit-billing-runbook.md`
- Create: `scripts/db/check_billing_invariants.py`
- Test: `tests/unit/scripts/test_check_billing_invariants.py`

**Interfaces:**
- Invariant checker exits nonzero for projection mismatch, duplicate financial effect, negative balance, paid-without-grant, or stuck-order threshold breach.

- [ ] Write failing invariant-checker tests with one fixture per failure class.
- [ ] Implement read-only checker and runbook commands for backup, shadow comparison, pilot allowlist, enforcement switch, rollback to shadow, and reconciliation export.
- [ ] Run a seven-day shadow window containing at least 1,000 text supplier calls, 100 image jobs, and 20 video jobs; require zero duplicate financial effects, zero negative balances, and fewer than 0.1 percent unresolved evidence rows before pilot approval.
- [ ] Enable enforced mode for an explicit pilot allowlist for 72 hours; require zero projection mismatches and zero paid-without-grant orders, then enable recharge for newly registered customers while existing customers remain in shadow mode until an announced migration date.
- [ ] Commit with message `docs: add credit billing rollout runbook`.
