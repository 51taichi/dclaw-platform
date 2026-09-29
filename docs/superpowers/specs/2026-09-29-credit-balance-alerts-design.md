# Credit Balance Alerts Design

**Date:** 2026-09-29

**Status:** Approved for implementation planning

**Repositories:** `dclaw-server`, `dclaw-client/console`

## Goal

Add customer identity fields and two-level low-credit alerts without changing
the behavior or contracts of existing authentication, wallet, charging, top-up,
or client workflows. The first release records SMS notification events but does
not send SMS. A later release can enable Volcengine SMS by supplying an adapter
and configuration.

## Confirmed Product Decisions

- The administrator supplies a display name and mobile number when creating a
  user. The display name is separate from the login ID.
- Mobile ownership is not verified by SMS or another OTP flow.
- Every customer starts with a warning threshold of 5,000 credits and a
  critical threshold of 1,000 credits.
- Customers, not administrators, can change their own thresholds.
- The warning threshold must be greater than the critical threshold, and the
  critical threshold must be non-negative.
- A client alert remains visible until the customer dismisses that tier by
  choosing “Do not remind me again.”
- Dismissing the warning tier does not suppress a later critical-tier alert.
- Recharging above a tier's threshold rearms that tier. A later downward
  crossing alerts again.
- SMS is generated once per downward threshold crossing, not on every balance
  read or while the balance remains below the threshold.
- The first release does not send real SMS.

## Scope

### Included

- User display name and mobile number in the admin create-user flow and user
  list.
- Per-user warning and critical thresholds with 5,000/1,000 defaults.
- A customer-facing threshold editor on the wallet page.
- A persistent orange warning or red critical banner in the authenticated web
  and desktop console.
- Durable alert, dismissal, rearm, and SMS-event state.
- A provider-neutral SMS sender contract and a disabled first-release sender.
- Backward-compatible schema upgrades and API evolution.
- Backend, frontend, migration, concurrency, and regression tests.
- Operational documentation for enabling Volcengine SMS later.

### Excluded from the first release

- Sending a real SMS.
- SMS verification of mobile ownership.
- Administrator-managed per-user thresholds.
- Editing identity fields after account creation.
- Backfilling names or mobile numbers for existing users.
- Miniapp-specific warning UI.
- Marketing messages, URLs in SMS content, or international sender-ID flows.

## Architecture

The existing wallet and immutable ledger remain the financial source of truth.
A new credit-alert service observes the committed wallet balance, reconciles it
against durable per-tier state, and records an idempotent notification event
when a tier is crossed. Alert processing is deliberately outside the financial
commit: an alert failure must never roll back, delay, or invalidate a charge or
top-up. If immediate post-commit reconciliation fails, the next alert-status
read, wallet refresh, or periodic reconciliation retries from the durable
wallet and tier state.

The console reads a customer-scoped alert resource after login, after local
billing-settlement events, and on a 60-second fallback interval. It renders the
most severe active, non-dismissed tier above the routed page. Dismissal is
stored on the server so it is consistent across browser sessions and devices.

No external network call exists in the first release. The SMS sender boundary
returns a deterministic disabled result, and the event is finalized as
`skipped_unconfigured`, so enabling SMS later cannot send stale historical
alerts.

## Data Model

### Existing `users` table

Add nullable columns:

- `display_name`: trimmed human-readable name, maximum 100 characters.
- `phone_number_e164`: normalized mobile number, maximum 32 characters.

Both columns are nullable so legacy users, the first-user registration flow,
environment-created administrators, and older API clients continue working.
The new console create-user form requires both values. The admin API accepts
them as optional during the compatibility release.

For this release, input accepts either a mainland China 11-digit mobile number
or the equivalent `+86` form and persists it as `+86xxxxxxxxxxx`. This is format
normalization only; it is not proof of ownership. The number is not unique
because multiple accounts may intentionally share a billing contact.

### `credit_alert_preferences`

One row per user:

- `user_id`: primary key and foreign key to `users.id`.
- `warning_threshold`: non-negative bigint, default 5,000.
- `critical_threshold`: non-negative bigint, default 1,000.
- `created_at`, `updated_at`.

The service enforces `warning_threshold > critical_threshold >= 0`. A row is
created with a new user and lazily for legacy users on first access.

### `credit_alert_states`

One row per `(user_id, tier)`, where `tier` is `warning` or `critical`:

- `status`: `armed`, `active`, `dismissed`, or `superseded`.
- `cycle_number`: monotonically increasing alert cycle for idempotency.
- `activation_source`: `crossing` or `reconciliation`, nullable while armed.
- `trigger_balance`: balance that activated the current cycle, nullable.
- `triggered_at`, `dismissed_at`, `rearmed_at`, `updated_at`.

`armed` means a future downward crossing may activate the tier. `active` is
visible in the client. `dismissed` remains quiet until rearmed. `superseded`
prevents a lower-severity banner or SMS from appearing after a more severe tier
has become active in the same low-balance episode.

### `credit_alert_events`

One durable notification record per alert cycle:

- Stable event ID.
- `user_id`, `tier`, `cycle_number`.
- Balance and threshold snapshots.
- Display-name and normalized-phone snapshots, nullable for legacy users.
- `sms_status`: `skipped_unconfigured`, `skipped_missing_phone`, `pending`,
  `submitted`, `delivered`, or `failed`.
- Provider message ID, provider error summary, attempt count, and timestamps.

A unique constraint on `(user_id, tier, cycle_number)` prevents duplicate
events under concurrent evaluation. Provider credentials and secrets are never
stored in this table.

User deletion explicitly removes alert preferences, states, and events before
deleting the user, matching the repository's existing manual cascade pattern.

## Alert State Machine

### Downward crossing

A tier crosses when the last reconciled balance was above its threshold and
the new committed balance is at or below it while the tier is armed.

- Crossing the warning tier activates an orange warning and records one warning
  event.
- A later crossing of the critical tier activates a red critical alert,
  supersedes the warning tier for the current low-balance episode, and records
  one critical event.
- If one balance change crosses both tiers, only the critical tier produces an
  event; the warning tier is marked superseded. This prevents two SMS messages
  and prevents an orange banner from appearing immediately after the red banner
  is dismissed.

### Initial and configuration reconciliation

A new empty wallet or a legacy wallet first observed below a threshold displays
the appropriate client alert but does not produce an SMS event. Likewise,
raising a threshold above the current balance makes the corresponding client
alert visible but does not retroactively create an SMS event. These states are
tagged as reconciliation rather than a spending-driven crossing.

### Dismissal

The customer can dismiss only the currently displayed tier. The state becomes
`dismissed` and remains hidden across refreshes and devices. Reaching a more
severe tier still displays that new tier.

### Rearming

When the available balance becomes strictly greater than a tier's current
threshold, that tier returns to `armed`, clears dismissal metadata, and becomes
eligible for a future crossing. A balance exactly equal to a threshold remains
inside that tier.

Changing thresholds runs the same reconciliation after preferences are saved.
It can display or clear client state immediately, but it never generates a
spending SMS event by itself.

## API Design

All routes remain under the existing authenticated admin or user router.

### Admin users

- `GET /api/admin/users` keeps all existing fields and additionally returns
  `display_name` and `phone_number`.
- `POST /api/admin/users` additionally accepts optional `display_name` and
  `phone_number`. The new console form requires them; optional server fields
  keep older clients and scripts compatible.
- Existing password reset and delete routes retain their paths and behavior.

### Customer credit alerts

- `GET /api/user/billing/credit-alerts` returns normalized preferences, current
  available balance, and the most severe visible alert or `null`.
- `PATCH /api/user/billing/credit-alerts/preferences` accepts both thresholds,
  validates them atomically, saves them, reconciles against the current balance,
  and returns the same resource representation.
- `POST /api/user/billing/credit-alerts/{tier}/dismiss` dismisses an active tier
  idempotently and returns the updated resource. Unknown tiers return 404;
  invalid or non-active transitions return a stable 409 response.

The server resolves `user_id` exclusively from the authenticated request. A
caller cannot read or change another customer's preferences or dismissal
state.

Existing auth, wallet, ledger, quote, top-up, and admin billing endpoints are
unchanged.

## Console Design

### Admin user management

The create-user modal contains:

1. Login ID (the existing `username`).
2. Display name.
3. Mobile number.
4. Password.
5. Role.

The display name and mobile number are required in the new UI. The table adds
display-name and mobile-number columns while retaining ID, login ID, role,
creation time, reset-password, and delete behavior.

### Customer wallet settings

The wallet page adds a “Credit alert settings” card with integer inputs for the
warning and critical thresholds. It explains the defaults and the ordering
rule, validates locally, and displays server validation failures without
altering the last saved values.

### Persistent banner

A credit-alert provider mounted in `ClientLayout` fetches alert state:

- immediately when the authenticated layout mounts;
- after `dclaw:billing-settled`;
- after preference save or dismissal; and
- every 60 seconds as a cross-device fallback.

An orange banner represents `warning`; a red, visually stronger banner
represents `critical`. The banner shows the available balance and threshold and
offers “Top up” and “Do not remind me again.” “Top up” navigates to `/wallet`.
The banner stays outside routed page content so navigation cannot hide it.

If the alert endpoint is temporarily unavailable, the client hides stale alert
actions, leaves the rest of the application usable, and retries at the next
normal refresh. It does not fabricate a zero balance.

## SMS Boundary and Volcengine Phase Two

The server defines a provider-neutral sender interface that consumes an event
snapshot and returns a structured submission result. The first release binds a
disabled sender and makes no network requests.

The future Volcengine adapter uses these environment-backed settings:

- `DCLAW_VOLCENGINE_SMS_ENABLED`
- `DCLAW_VOLCENGINE_SMS_ACCESS_KEY_ID`
- `DCLAW_VOLCENGINE_SMS_SECRET_ACCESS_KEY`
- `DCLAW_VOLCENGINE_SMS_ACCOUNT`
- `DCLAW_VOLCENGINE_SMS_SIGN`
- `DCLAW_VOLCENGINE_SMS_TEMPLATE_ID`

Enabling the adapter affects only newly created crossing events. It never
requeues `skipped_unconfigured` history.

The operations sequence is:

1. Open Volcengine SMS and create a message group.
2. Submit company qualifications, a compliant signature, and a notification
   template. Allow time for platform review and operator registration.
3. Install the official `volcengine` Python SDK in a separately reviewed
   dependency change.
4. Supply credentials through the deployment secret store or environment, not
   source control, database rows, browser configuration, or logs.
5. Call `SendSms` with `SmsAccount`, `Sign`, `TemplateID`, `TemplateParam`,
   `PhoneNumbers`, and the event ID in `Tag`.
6. Optionally expose a dedicated delivery-receipt endpoint and configure it in
   the Volcengine console. Match the callback `ext` value to the event ID and
   update delivery status idempotently.

Recommended template content contains no URL:

> 您的账户当前可用积分为${balance}，已达到${threshold}积分预警线，请及时充值。

Official references:

- [Signature review requirements](https://www.volcengine.com/docs/6361/170338?lang=zh)
- [Python SDK example](https://docs.volcengine.com/docs/SMSservice/PythonSDK-4?lang=zh)
- [SendSms API](https://www.volcengine.com/docs/6361/67380?lang=zh)
- [Delivery status callback](https://docs.volcengine.com/docs/SMSservice/SMSstatusreportcallback?lang=zh)

## Failure Handling and Compatibility

- Schema additions are nullable or new tables; no existing user row is
  rewritten or made invalid.
- The compatibility release does not require new fields from older admin API
  callers.
- Additional response fields are additive. Existing fields keep their names,
  types, and meanings.
- Alert reconciliation occurs after a financial commit and is retryable. Its
  failure cannot roll back a charge, release, capture, grant, or top-up.
- SMS submission is asynchronous to financial behavior. Provider timeout,
  rejection, or outage cannot change a wallet balance.
- Event uniqueness and state locking prevent duplicate notifications during
  concurrent debits or reconciliation.
- Missing legacy mobile numbers produce `skipped_missing_phone`; the console
  alert still works.
- Logs may include user ID, event ID, tier, and provider error code but must not
  include AK/SK values or an unmasked full mobile number.
- Existing mobile and miniapp API behavior is unchanged.

## Testing and Acceptance Criteria

### Server

- Schema creation and upgrade tests cover SQLite and PostgreSQL-compatible DDL.
- Repository tests cover new-user values, nullable legacy values, normalization,
  defaults, validation, deletion, and authorization isolation.
- State-machine tests cover warning crossing, critical crossing, one debit
  crossing both tiers, equality boundaries, dismissal, lower-tier escalation,
  rearming after top-up, threshold edits, and initial zero balance.
- Concurrency tests prove a single event for the same user, tier, and cycle.
- Failure-injection tests prove alert and SMS failures do not alter successful
  wallet transactions.
- Existing authentication, admin users, billing, top-up, and migration suites
  remain green.

### Console

- Admin form tests prove display name and mobile are required and submitted.
- User-table tests prove the new fields render without removing existing
  actions.
- Wallet tests cover loading, successful save, invalid ordering, and server
  errors.
- Banner tests cover warning/critical appearance, persistence across route
  changes, dismissal, escalation, refresh triggers, wallet navigation, and
  unavailable API behavior.
- The full Vitest suite, TypeScript check, lint, and production build pass.

### End-to-end acceptance

- A legacy user can log in and use the existing product after migration.
- A newly created user retains login ID, name, and normalized mobile number.
- A customer can change only their own thresholds.
- The banner follows the confirmed dismissal and rearm rules across reloads.
- Each spending-driven crossing creates at most one SMS event.
- First-release execution performs no SMS network request.
- Disabling or breaking the alert subsystem does not break wallet or product
  use.

## Rollout

1. Deploy the backward-compatible server schema and endpoints.
2. Deploy the updated console and rebuild the packaged static assets consumed
   by `dclaw-server`.
3. Keep Volcengine SMS disabled and verify alert events are recorded as skipped.
4. Review event counts, client behavior, and wallet regression metrics.
5. Implement and enable the Volcengine adapter only after credentials, message
   group, signature, template, rate limits, and delivery monitoring are ready.
