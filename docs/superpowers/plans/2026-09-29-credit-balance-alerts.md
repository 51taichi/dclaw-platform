# Credit Balance Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add customer name/mobile data, configurable 5,000/1,000 credit alerts, persistent client banners, and a disabled-but-durable SMS notification boundary without changing existing billing behavior.

**Architecture:** The wallet ledger stays authoritative. New alert tables and a focused `CreditAlertService` maintain per-tier state from wallet changes, while a savepoint isolates alert failures from the enclosing financial transaction. The adjacent React console consumes customer-scoped alert APIs; the first release records terminal `skipped_*` SMS events and performs no network request.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite/PostgreSQL, pytest; React 18, TypeScript 5.8, Ant Design 5, Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-29-credit-balance-alerts-design.md`

## Global Constraints

- Use isolated worktrees for both `dclaw-server` and `dclaw-client` at execution time; preserve the dirty client checkout (`VERSION` and `console/src-tauri/*`) and the untracked server `outputs/` directory.
- Existing auth, wallet, ledger, quote, top-up, admin billing, mobile, and miniapp endpoint paths and field meanings must remain unchanged.
- Database upgrades must accept legacy users with no display name or mobile number; older admin API clients may omit both new fields.
- New console-created users require a display name and mainland-China mobile number, normalized to `+86xxxxxxxxxxx`, without OTP verification or uniqueness enforcement.
- Default thresholds are exactly warning `5000` and critical `1000`; enforce `0 <= critical < warning <= 9,223,372,036,854,775,807`.
- A current-tier dismissal persists server-side, a more severe tier can still alert, and a tier rearms only after available credits become strictly greater than its threshold.
- One balance change that crosses both tiers produces only a critical SMS event and supersedes the warning tier for that low-balance episode.
- Initial-zero and preference-change reconciliation may show a banner but must not create a spending SMS event.
- No first-release code may install the Volcengine SDK, read production AK/SK values, or perform an SMS network request.
- Alert persistence or sender failure must not roll back or invalidate a successful financial mutation.
- Do not manually edit generated files under `src/qwenpaw/console`; the combined build/release workflow owns client artifact synchronization.

## Review Focus

- **Legacy create caller omits identity fields:** creation still succeeds with `null` identity values; Task 2 adds this compatibility test.
- **Concurrent evaluators observe one crossing:** the unique `(user_id, tier, cycle_number)` event survives races without duplicates; Task 3 adds the concurrency test.
- **Exact and double-threshold boundaries:** `5001 -> 5000` warns, while `6000 -> 500` records only critical; Task 3 pins both cases.
- **Alert write raises inside billing:** the ledger mutation and resulting balance still commit; Task 4 adds failure injection around the alert savepoint.
- **No phone or disabled channel:** the event is terminally `skipped_missing_phone` or `skipped_unconfigured` and no sender/network call occurs; Task 3 adds both tests.

---

### Task 1: Durable identity and alert schema

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/db.py`
- Modify: `src/qwenpaw/app/storage/repos/user_repo.py`
- Create: `src/qwenpaw/app/user_identity.py`
- Modify: `tests/unit/app/storage/test_schema.py`
- Modify: `tests/unit/app/storage/repos/test_user_repo.py`

**Interfaces:**
- Produces: `normalize_cn_mobile(value: str | None) -> str | None`.
- Produces: `UserRepository.create_user(..., display_name: str | None = None, phone_number_e164: str | None = None) -> dict[str, Any]` while preserving all existing callers.
- Produces: SQLAlchemy tables `credit_alert_preferences`, `credit_alert_states`, and `credit_alert_events` with the columns and constraints from the spec.

- [ ] **Step 1: Write failing schema and repository tests**

Add literal assertions that a twice-run `create_all()` upgrades a legacy `users` table with nullable `display_name` and `phone_number_e164`, creates all three alert tables, installs the event uniqueness constraint, and keeps legacy rows readable. Extend repository tests so new identity values round-trip while an old `create_user(username=..., password_hash=..., password_salt=..., role=...)` call returns both new keys as `None`. Add table-backed deletion assertions for alert rows.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/unit/app/storage/test_schema.py tests/unit/app/storage/repos/test_user_repo.py -q`

Expected: FAIL because the columns/tables, new repository arguments, and normalized identity fields do not exist.

- [ ] **Step 3: Add the additive schema and idempotent migration**

Define both nullable user columns and the three alert tables in `schema.py`; call a new `_ensure_user_identity_columns(engine: Engine) -> None` from `create_all()`. Update the legacy SQLite `CREATE TABLE users` declaration and its idempotent column upgrade in `db.py`. Use bigint thresholds/balance snapshots, constrained tier/status/source values, foreign keys to `users.id`, and the event unique key specified by the design.

- [ ] **Step 4: Implement mobile normalization and repository parity**

Implement `normalize_cn_mobile` to accept `1[3-9][0-9]{9}` or `+861[3-9][0-9]{9}`, trim surrounding whitespace, return canonical `+86...`, return `None` for `None`, and raise `ValueError` for malformed non-null values. Extend both SQLAlchemy and sqlite repositories, their protocol, selects, inserts, lists, and manual delete cascades without changing credential queries.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/unit/app/storage/test_schema.py tests/unit/app/storage/repos/test_user_repo.py -q`

Expected: PASS with repeatable schema creation and unchanged legacy-user behavior.

- [ ] **Step 6: Commit the server schema slice**

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/db.py \
  src/qwenpaw/app/storage/repos/user_repo.py src/qwenpaw/app/user_identity.py \
  tests/unit/app/storage/test_schema.py tests/unit/app/storage/repos/test_user_repo.py
git commit -m "feat: add credit alert storage"
```

### Task 2: Backward-compatible admin user identity API

**Files:**
- Modify: `src/qwenpaw/app/routers/admin_users.py`
- Modify: `tests/unit/app/routers/test_admin_users_repo.py`

**Interfaces:**
- Consumes: `normalize_cn_mobile` and the extended `UserRepository` from Task 1.
- Produces: additive `display_name: str | None` and `phone_number: str | None` fields in `UserSpec`.
- Produces: optional `display_name` and `phone_number` inputs in `CreateUserRequest`.

- [ ] **Step 1: Write failing API behavior tests**

Extend the fake repository and tests to assert that whitespace-trimmed `display_name="Alice Chen"` and `phone_number="13800138000"` are stored/returned as `Alice Chen` and `+8613800138000`; malformed mobile input returns HTTP 422 without creating a user or wallet. Add the Review Focus test proving an old request with only username/password/role still succeeds and returns `None` for both additive fields.

- [ ] **Step 2: Run the router tests and verify RED**

Run: `python -m pytest tests/unit/app/routers/test_admin_users_repo.py -q`

Expected: FAIL because the request/response models and repository call do not carry identity fields.

- [ ] **Step 3: Implement the additive request/response contract**

Add Pydantic length limits, trim the display name, normalize a supplied phone number, pass normalized values into the repository, and serialize the two new response fields from both list and create routes. Keep both request fields optional on the server and preserve duplicate-user wallet recovery.

- [ ] **Step 4: Run the router tests and verify GREEN**

Run: `python -m pytest tests/unit/app/routers/test_admin_users_repo.py -q`

Expected: PASS, including the legacy request and invalid-phone cases.

- [ ] **Step 5: Commit the server API slice**

```bash
git add src/qwenpaw/app/routers/admin_users.py \
  tests/unit/app/routers/test_admin_users_repo.py
git commit -m "feat: capture customer identity on user creation"
```

### Task 3: Credit alert state machine and disabled SMS boundary

**Files:**
- Create: `src/qwenpaw/app/notifications/__init__.py`
- Create: `src/qwenpaw/app/notifications/sms.py`
- Create: `src/qwenpaw/app/storage/repos/credit_alert_repo.py`
- Create: `src/qwenpaw/app/billing/credit_alerts.py`
- Create: `tests/unit/app/billing/test_credit_alerts.py`
- Create: `tests/unit/app/storage/repos/test_credit_alert_repo.py`

**Interfaces:**
- Produces: `SmsAlert`, `SmsSubmissionResult`, `SmsSender.send(alert: SmsAlert) -> SmsSubmissionResult`, and `DisabledSmsSender` that never performs I/O.
- Produces: `CreditAlertService.get(user_id: int, available: int) -> dict[str, Any]`.
- Produces: `CreditAlertService.update_preferences(user_id: int, warning_threshold: int, critical_threshold: int, available: int) -> dict[str, Any]`.
- Produces: `CreditAlertService.dismiss(user_id: int, tier: str, available: int) -> dict[str, Any]`.
- Produces: `CreditAlertService.reconcile_in_connection(conn: Connection, wallet_id: str, available: int, *, cause: Literal["balance_change", "expiry", "reconciliation", "preference_change"]) -> None`.

- [ ] **Step 1: Write failing repository and state-machine tests**

Create fixtures with real SQLite tables and literal balances. Cover defaults, invalid ordering, initial zero as `reconciliation` with no event, `5001 -> 5000`, later `1001 -> 1000`, warning dismissal followed by critical escalation, rearm only at `threshold + 1`, preference-change activation without an event, and `6000 -> 500` producing exactly one critical event while warning is `superseded`.

- [ ] **Step 2: Add failing idempotency and channel-state tests**

Add a two-worker race test (or two independent connections coordinated by a barrier) that reconciles the same wallet crossing and asserts one event row. Add separate tests asserting a phone-less user yields `skipped_missing_phone`, a valid-phone user with `DisabledSmsSender` yields `skipped_unconfigured`, and the disabled sender has no HTTP/client dependency or call side effect.

- [ ] **Step 3: Run the new tests and verify RED**

Run: `python -m pytest tests/unit/app/billing/test_credit_alerts.py tests/unit/app/storage/repos/test_credit_alert_repo.py -q`

Expected: FAIL because the repository, service, state types, and SMS boundary do not exist.

- [ ] **Step 4: Implement the focused repository and sender contract**

Keep SQL statements and row-lock/idempotency mechanics in `CreditAlertRepository`; keep threshold decisions and tier transitions in `CreditAlertService`. Use `SELECT ... FOR UPDATE` where supported and unique-key recovery for concurrent first insertion. Snapshot identity/balance/threshold into each event and derive only the two terminal first-release statuses from phone presence and `DisabledSmsSender`.

- [ ] **Step 5: Implement the state machine minimally**

Follow the four states and four causes exactly. Increment `cycle_number` only for a spending/expiry crossing that earns an event. Choose the most severe active non-dismissed tier for the returned resource. When critical activates, mark warning `superseded`; do not allow dismissing a tier that is not the visible active tier.

- [ ] **Step 6: Run the new tests and verify GREEN**

Run: `python -m pytest tests/unit/app/billing/test_credit_alerts.py tests/unit/app/storage/repos/test_credit_alert_repo.py -q`

Expected: PASS with one event per cycle and zero external requests.

- [ ] **Step 7: Commit the alert domain slice**

```bash
git add src/qwenpaw/app/notifications src/qwenpaw/app/billing/credit_alerts.py \
  src/qwenpaw/app/storage/repos/credit_alert_repo.py \
  tests/unit/app/billing/test_credit_alerts.py \
  tests/unit/app/storage/repos/test_credit_alert_repo.py
git commit -m "feat: add durable credit alert state machine"
```

### Task 4: Wire wallet mutations and customer alert APIs

**Files:**
- Modify: `src/qwenpaw/app/storage/repos/billing_repo.py`
- Modify: `src/qwenpaw/app/routers/billing.py`
- Modify: `tests/unit/app/storage/repos/test_billing_repo.py`
- Modify: `tests/unit/app/routers/test_billing.py`

**Interfaces:**
- Consumes: `CreditAlertService.reconcile_in_connection` from Task 3.
- Produces: `GET /api/user/billing/credit-alerts`.
- Produces: `PATCH /api/user/billing/credit-alerts/preferences` with `{warning_threshold: int, critical_threshold: int}`.
- Produces: `POST /api/user/billing/credit-alerts/{tier}/dismiss`.
- Produces resource shape: `{preferences: {warning_threshold, critical_threshold}, available, alert: null | {tier, threshold, available, triggered_at}}`.

- [ ] **Step 1: Write failing billing-hook tests**

Add a real-repository test that creates a real user/wallet, grants 6,000, then holds through 5,000 and asserts the warning state/event was written in the same outer transaction. Add expiry reconciliation coverage. Add failure injection that makes alert reconciliation raise inside its nested savepoint and asserts the ledger entry and resulting wallet balance still commit.

- [ ] **Step 2: Write failing customer-route tests**

Extend the existing FastAPI test app to assert authenticated-owner isolation, exact defaults, successful preference replacement, reversed/equal/negative/greater-than-bigint rejection, unknown-tier 404, non-visible-tier 409, repeated dismissal of the already-dismissed visible tier returning 200 with unchanged state, and response values derived from the authenticated user's real wallet rather than request input.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `python -m pytest tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/routers/test_billing.py -q`

Expected: FAIL because ledger mutations do not reconcile alerts and the three routes are absent.

- [ ] **Step 4: Add best-effort reconciliation to the ledger boundary**

At the end of `append_transaction_in_connection`, invoke alert reconciliation in `conn.begin_nested()` using the computed available balance and `balance_change`; catch/log alert-only exceptions so the caller's transaction remains usable. Make `_expire_available_lots` report whether it changed available credit and reconcile changed expiry balances with cause `expiry`. Do not call `SmsSender` or any network service from this path.

- [ ] **Step 5: Implement the customer-scoped route handlers**

Add strict Pydantic request models, resolve owner only through `_authenticated_owner`, read the real wallet balance, translate service validation/conflict errors into stable 404/409/422 responses, and return the shared resource representation after get/update/dismiss.

- [ ] **Step 6: Run focused and server regression tests**

Run: `python -m pytest tests/unit/app/storage/repos/test_billing_repo.py tests/unit/app/routers/test_billing.py tests/unit/app/billing/test_top_up_service.py tests/integration/test_console_billing_flow.py tests/integration/test_open_api_billing_flow.py -q`

Expected: PASS; existing billing balances and idempotency assertions remain unchanged.

- [ ] **Step 7: Commit the server integration slice**

```bash
git add src/qwenpaw/app/storage/repos/billing_repo.py \
  src/qwenpaw/app/routers/billing.py \
  tests/unit/app/storage/repos/test_billing_repo.py \
  tests/unit/app/routers/test_billing.py
git commit -m "feat: expose customer credit alerts"
```

### Task 5: Add identity fields to the console admin flow

**Files (in the `dclaw-client` repository):**
- Modify: `console/src/api/modules/adminUsers.ts`
- Modify: `console/src/pages/Settings/Users/index.tsx`
- Modify: `console/src/pages/Settings/Users/Users.test.tsx`
- Modify: `console/src/pages/Settings/Users/index.module.less` only if the wider table needs a responsive rule.

**Interfaces:**
- Consumes: additive admin API fields from Task 2.
- Produces: typed `CreateAdminUserInput` and removes the existing `any` request body.

- [ ] **Step 1: Write failing form and table tests**

Render the real page, open “创建用户,” and assert labels “登录 ID,” “姓名,” and “手机号.” Submit valid values and assert the API receives `{username, display_name, phone_number, password, role}`. Add required-field and malformed-mobile UI tests, and assert returned name/mobile columns render while reset/delete actions remain available.

- [ ] **Step 2: Run the page test and verify RED**

Run from `dclaw-client/console`: `npm run test:run -- src/pages/Settings/Users/Users.test.tsx`

Expected: FAIL because the form, columns, response type, and typed input are absent.

- [ ] **Step 3: Implement typed API and UI fields**

Extend `AdminUser`, introduce `CreateAdminUserInput`, and type `createUser`. Rename only the visible username label to “登录 ID”; keep the wire key `username`. Require/trim display name and accept the same two mainland mobile forms as the server, leaving the server authoritative.

- [ ] **Step 4: Run focused tests and typecheck**

Run from `dclaw-client/console`: `npm run test:run -- src/pages/Settings/Users/Users.test.tsx && npx tsc -b --noEmit`

Expected: PASS with no TypeScript errors.

- [ ] **Step 5: Commit the client admin slice without staging existing Tauri/VERSION changes**

```bash
git add console/src/api/modules/adminUsers.ts \
  console/src/pages/Settings/Users/index.tsx \
  console/src/pages/Settings/Users/Users.test.tsx \
  console/src/pages/Settings/Users/index.module.less
git commit -m "feat(console): collect customer identity"
```

### Task 6: Add customer alert API types and wallet settings

**Files (in the `dclaw-client` repository):**
- Modify: `console/src/api/types/billing.ts`
- Modify: `console/src/api/modules/billing.ts`
- Modify: `console/src/api/modules/billing.test.ts`
- Create: `console/src/pages/Wallet/components/CreditAlertSettings.tsx`
- Create: `console/src/pages/Wallet/components/CreditAlertSettings.test.tsx`
- Modify: `console/src/pages/Wallet/index.tsx`
- Modify: `console/src/pages/Wallet/index.module.less`
- Modify: `console/src/pages/Wallet/WalletPage.test.tsx`

**Interfaces:**
- Consumes: the three alert endpoints and resource shape from Task 4.
- Produces: `CreditAlertResource`, `CreditAlertPreferences`, and `CreditAlert` TypeScript interfaces.
- Produces: `billingApi.getCreditAlerts`, `billingApi.updateCreditAlertPreferences`, and `billingApi.dismissCreditAlert`.

- [ ] **Step 1: Write failing request-contract tests**

Assert exact paths/methods/bodies for get, preference patch, and tier dismissal using the existing request mock conventions in `billing.test.ts`.

- [ ] **Step 2: Write failing settings component tests**

Assert the independent card loads 5,000/1,000, saves literal integers, blocks equal/reversed/negative values, preserves saved values after a server error, and dispatches `dclaw:credit-alert-changed` only after success. Extend `WalletPage.test.tsx` so an alert-settings fetch failure does not replace or block the existing wallet/top-up/history UI.

- [ ] **Step 3: Run focused tests and verify RED**

Run from `dclaw-client/console`: `npm run test:run -- src/api/modules/billing.test.ts src/pages/Wallet/components/CreditAlertSettings.test.tsx src/pages/Wallet/WalletPage.test.tsx`

Expected: FAIL because the API methods, types, and card do not exist.

- [ ] **Step 4: Implement the typed requests and isolated settings card**

Add types and methods, then mount `CreditAlertSettings` as its own error boundary within the wallet page rather than adding its request to the page's existing `Promise.all`. Use Ant Design integer controls and server-returned values; do not derive authoritative alert state in the browser.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run from `dclaw-client/console`: `npm run test:run -- src/api/modules/billing.test.ts src/pages/Wallet/components/CreditAlertSettings.test.tsx src/pages/Wallet/WalletPage.test.tsx`

Expected: PASS, including the independent-failure regression.

- [ ] **Step 6: Commit the client wallet-settings slice**

```bash
git add console/src/api/types/billing.ts console/src/api/modules/billing.ts \
  console/src/api/modules/billing.test.ts console/src/pages/Wallet
git commit -m "feat(console): add credit alert settings"
```

### Task 7: Add the persistent client alert banner

**Files (in the `dclaw-client` repository):**
- Create: `console/src/features/billing/CreditAlertBanner.tsx`
- Create: `console/src/features/billing/CreditAlertBanner.module.less`
- Create: `console/src/features/billing/CreditAlertBanner.test.tsx`
- Modify: `console/src/layouts/ClientLayout/index.tsx`
- Modify: `console/src/layouts/ClientLayout.test.tsx`
- Modify: `console/src/layouts/index.module.less`

**Interfaces:**
- Consumes: `billingApi.getCreditAlerts` and `billingApi.dismissCreditAlert` from Task 6.
- Consumes: window events `dclaw:billing-settled` and `dclaw:credit-alert-changed`.
- Produces: a route-persistent banner that refreshes on mount/events and every 60 seconds.

- [ ] **Step 1: Write failing banner behavior tests**

Using fake timers and the real router, assert no banner for `alert: null`, orange warning and red critical content for literal resources, `/wallet` navigation from “去充值,” persistence across route navigation, dismissal only after a successful server response, event-driven refresh, 60-second refresh, and recovery after a temporary fetch failure without showing a fabricated zero.

- [ ] **Step 2: Add the failing layout regression**

Update `ClientLayout.test.tsx` to prove the banner mounts above routed content and task-route state remains mounted during navigation. Mock only the API boundary, not the banner component behavior in the dedicated banner test.

- [ ] **Step 3: Run focused tests and verify RED**

Run from `dclaw-client/console`: `npm run test:run -- src/features/billing/CreditAlertBanner.test.tsx src/layouts/ClientLayout.test.tsx`

Expected: FAIL because the banner and layout slot are absent.

- [ ] **Step 4: Implement the banner and refresh lifecycle**

Render the most severe resource returned by the server with Ant Design `Alert`, use warning/error styling and accessible action labels, clear timers/listeners on unmount, keep the last confirmed resource out of action state after request failure, and re-fetch after dismissal rather than predicting the next tier locally.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run from `dclaw-client/console`: `npm run test:run -- src/features/billing/CreditAlertBanner.test.tsx src/layouts/ClientLayout.test.tsx`

Expected: PASS without timer leaks or React act warnings.

- [ ] **Step 6: Commit the client banner slice**

```bash
git add console/src/features/billing/CreditAlertBanner* \
  console/src/layouts/ClientLayout/index.tsx \
  console/src/layouts/ClientLayout.test.tsx console/src/layouts/index.module.less
git commit -m "feat(console): show persistent low credit alerts"
```

### Task 8: Document Volcengine enablement and run release gates

**Files:**
- Create: `docs/operations/volcengine-credit-alert-sms.md`
- Modify: `docs/operations/dclaw-container-release.md` only if it maintains an environment-variable allowlist.
- Verify only: generated client `console/dist/**`; do not commit it.
- Verify only: packaged server `src/qwenpaw/console/**`; update only through the established combined build/release workflow, not manual edits.

**Interfaces:**
- Consumes: `SmsSender` and event statuses from Task 3.
- Produces: an operator runbook for phase-two enablement; no runnable Volcengine adapter in this change.

- [ ] **Step 1: Write the operations runbook**

Document message-group creation, qualification/signature/template approval, the six `DCLAW_VOLCENGINE_SMS_*` settings, secret-storage requirements, the approved no-URL template, `SendSms` request mapping, event ID in `Tag`, delivery callback mapping, rate limits, canary checks, rollback by disabling the flag, and the rule that skipped historical events are never replayed. Link the four official references from the design.

- [ ] **Step 2: Run the complete server verification gate**

Run from `dclaw-server`:

```bash
python -m pytest tests/ -q
ruff check src/qwenpaw/app tests/unit/app tests/integration
git diff --check
```

Expected: all tests and lint checks pass. If the repository-wide suite has a pre-existing failure, record its exact test name and reproduce it on the untouched base before classifying it as unrelated.

- [ ] **Step 3: Run the complete client verification gate**

Run from `dclaw-client/console`:

```bash
npm run test:run
npx tsc -b --noEmit
npm run lint
npm run build
```

Expected: all tests, typecheck, lint, and production build pass; `console/dist` contains the new compiled UI.

- [ ] **Step 4: Verify both worktrees contain only intended changes**

Run `git status --short`, `git diff --check`, and `git log --oneline -8` in each repository. Confirm the original dirty `VERSION`/Tauri files and server `outputs/` were neither staged nor modified by this work.

- [ ] **Step 5: Commit the runbook in the server repository**

```bash
git add docs/operations/volcengine-credit-alert-sms.md \
  docs/operations/dclaw-container-release.md
git commit -m "docs: explain Volcengine credit alert SMS setup"
```

- [ ] **Step 6: Perform completion review**

Use `superpowers:requesting-code-review`, address findings with test-first fix cycles, then use `superpowers:verification-before-completion` before reporting completion or proposing integration.
