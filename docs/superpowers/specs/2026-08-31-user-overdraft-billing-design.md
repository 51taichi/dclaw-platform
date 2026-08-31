# User-level overdraft billing design

## Goal

Remove every runtime billing exception for the username `szzz_admin` and
replace it with a private, user-level overdraft capability. Every model call
must use the same published price catalog, usage metering, ledger, and report
pipeline. A user who is allowed to overdraw may continue when funded credits
are exhausted; every other user must still be stopped before supplier work.

This change applies to client, mobile, OpenAPI, expert-team, automation,
scheduled-task, external-channel, and AIGC calls. Historical complimentary
calls are not retroactively charged.

## Private account capability

The `users` table gains `billing_overdraft_enabled`, a non-null boolean with a
database default of false. It is intentionally absent from public DTOs,
authentication claims, client APIs, admin APIs, and the management UI.

The startup migration adds the column idempotently. Only while upgrading a
database that did not previously have the column, that same migration sets it
to true for the existing user whose username is `szzz_admin` and role is
`admin`. This is one-time migration data selection, not runtime policy.
Runtime billing code must not contain the username, role, or any equivalent
hard-coded bypass.

All billing entry points resolve the payer from trusted server-side context
and read the capability from the database. OpenAPI continues to use the
publication's bound user, never caller-supplied identity.

## Wallet and debt model

`billing_wallets` gains two non-negative projections:

- `debt_credits`: settled usage debt.
- `held_overdraft_credits`: provisional debt reserved for in-flight usage.

Existing funded credit lots remain non-negative and retain their expiry,
promotion, package, release, and allocation semantics. Debt is not represented
as a fabricated credit lot and cannot expire.

The public net balance is:

```
net_available = available_credits - debt_credits
```

The wallet response adds explicit `debt` and `held_overdraft` values while its
customer-facing available value is the signed `net_available`. Internal code
that allocates funded lots continues to use the stored non-negative funded
`available_credits` projection.

## Reservation and settlement

For a normal user, the current behavior is unchanged: a hold larger than
funded available credits fails atomically with insufficient credits.

For an overdraft-enabled user, a hold is split atomically:

1. Allocate as much as possible from eligible funded credit lots.
2. Record the remaining amount as held overdraft.
3. Increase the wallet's normal held projection by the funded portion and its
   `held_overdraft_credits` projection by the unfunded portion.
4. Persist both portions against the hold ledger entry so replay, release, and
   capture never recompute the split from current balances.

On billable capture, funded allocations are captured normally and the captured
overdraft portion moves from `held_overdraft_credits` to `debt_credits`. The
usage capture ledger entry records the complete charged amount, including the
debt portion, so model-consumption reporting and reconciliation show the true
charge.

On release or non-billable supplier outcome, funded allocations return to
their original lots and held overdraft is simply removed. No settled debt is
created. Partial capture/release follows the persisted allocation proportions
and preserves the existing idempotency rules.

The overdraft decision and wallet mutation occur in the same locked database
transaction. Concurrent requests may increase debt but cannot lose charges,
double-capture, or grant overdraft to a user whose capability was not observed
inside that transaction.

## Top-ups and grants

Every positive grant first repays settled debt in the same transaction. Only
the remainder creates a normal credit lot and increases funded available
credits. For example, a wallet with 10,000 debt receiving 30,000 credits ends
with zero debt and 20,000 funded available credits.

Debt repayment is recorded as an immutable ledger event linked to the grant's
business key. The original grant type and cash evidence remain available for
auditing. Replaying the same grant is idempotent and cannot repay debt twice.

Held overdraft is not repaid by a top-up because it is provisional. Once an
in-flight call settles, it either becomes debt or disappears; this avoids
changing the funding split underneath a running reservation.

## Removal of complimentary behavior

The coordinator and OpenAPI coordinator no longer switch selected users to
`observe`, create an internal complimentary catalog, emit a complimentary
reason, or generate zero-credit quotes. All users require an effective
published catalog and use the configured billing mode consistently.

Obsolete complimentary helpers, constants, fallback catalog creation, and
tests are removed. Existing internal complimentary catalog rows may remain
unreferenced; they are harmless historical data and are not selected or
published.

## Reporting and API behavior

Model usage orders continue to report quoted, captured, released, reconciling,
and actually debited credits. Debt-backed capture counts as an actual debit,
so overdraft calls no longer appear as zero-cost usage.

Wallet endpoints expose signed net available balance plus funded available,
debt, and held-overdraft details. Existing positive-balance users see the same
available value as before. No endpoint exposes or mutates the private user
capability.

## Migration and compatibility

PostgreSQL and SQLite startup migrations add all three columns idempotently:
`users.billing_overdraft_enabled`, `billing_wallets.debt_credits`, and
`billing_wallets.held_overdraft_credits`. New installations receive the same
schema through metadata creation. Existing wallet balances and credit lots are
unchanged.

The migration checks whether it created the capability column before running
the one-time `szzz_admin` backfill. If that user does not exist at that moment,
no user is enabled. Renaming the user later does not revoke the stored
capability. Creating a new user with the same username does not automatically
grant it.

## Failure handling and invariants

- Normal users can never create held or settled overdraft.
- Debt and held-overdraft projections can never be negative.
- Only settled, billable usage creates debt.
- Supplier failure and non-billable outcomes release provisional overdraft.
- Grants repay settled debt before creating spendable lots.
- Request replay, grant replay, capture replay, and release replay remain
  idempotent.
- Missing published pricing fails for every user; overdraft is not a pricing
  bypass.
- Disabling the private capability stops new overdraft immediately but does
  not erase existing debt or interrupt already persisted holds.

## Verification

Tests cover:

- schema defaults and idempotent PostgreSQL/SQLite migration;
- one-time capability backfill and absence of runtime username checks;
- normal-user insufficient-balance rejection;
- overdraft user funded-only, mixed funded/debt, and debt-only calls;
- OpenAPI resolution through the publication-bound payer;
- client, AIGC, background, expert-team, and scheduled entry-point behavior;
- billable capture, non-billable release, provider failure, and retry;
- concurrent holds and settlements;
- top-up smaller than, equal to, and larger than existing debt;
- ledger/report totals including debt-backed charges;
- signed wallet balance serialization;
- removal of complimentary zero-charge behavior.
