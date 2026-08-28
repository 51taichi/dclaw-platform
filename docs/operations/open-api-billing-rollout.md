# OpenAPI credit billing rollout and rollback

This runbook promotes OpenAPI billing through `shadow`, `observe`, and
`enforced` without back-charging historical traffic. Run it from the exact
production Compose directory. Replace every value in angle brackets before
executing a command. Do not copy production secrets into tickets or logs.

## 1. Record and back up the current production state

Create a restricted change directory outside Docker volumes and record the
change ticket, UTC time, operator, current source commit, Compose file, and
Nginx configuration.

```bash
install -d -m 0700 <change-dir>
date -u +%FT%TZ > <change-dir>/started-at.txt
git rev-parse HEAD > <change-dir>/source-commit.txt
git status --short > <change-dir>/source-status.txt
cp docker-compose.yml <change-dir>/docker-compose.yml
docker compose --profile saas config > <change-dir>/compose.rendered.yml
docker compose --profile saas ps --all > <change-dir>/compose.ps.txt
docker inspect qwenpaw-saas > <change-dir>/qwenpaw-saas.inspect.json
docker image inspect <current-image-ref> > <change-dir>/current-image.inspect.json
docker image save -o <change-dir>/current-image.tar <current-image-ref>
git bundle create <change-dir>/source.bundle --all
sudo nginx -T > <change-dir>/nginx.full.conf 2>&1
sudo nginx -t
```

Record the immutable image digest, not only a mutable tag. Keep the old image
locally until the observation window closes.

Back up PostgreSQL logically while it is healthy. The custom dump is the
authoritative business-data backup; the schema-only dump makes migration
review easier.

```bash
docker compose --profile saas exec -T postgres \
  pg_dump -U qwenpaw -d qwenpaw -Fc > <change-dir>/qwenpaw.pre-billing.dump
docker compose --profile saas exec -T postgres \
  pg_dump -U qwenpaw -d qwenpaw --schema-only \
  > <change-dir>/qwenpaw.pre-billing.schema.sql
docker compose --profile saas exec -T postgres \
  pg_restore -U qwenpaw -d postgres --list \
  < <change-dir>/qwenpaw.pre-billing.dump \
  > <change-dir>/qwenpaw.pre-billing.dump.list
```

Inventory and back up the named volumes `qwenpaw-data`, `qwenpaw-secrets`,
`qwenpaw-backups`, `qwenpaw-postgres`, and `qwenpaw-redis`. Treat the secrets
archive as highly sensitive. A filesystem copy of `qwenpaw-postgres` is only
valid from a stopped database or a storage-provider snapshot with PostgreSQL
consistency guarantees; it does not replace `pg_dump`.

```bash
docker volume inspect qwenpaw-data qwenpaw-secrets qwenpaw-backups \
  qwenpaw-postgres qwenpaw-redis > <change-dir>/volumes.inspect.json
docker run --rm -v qwenpaw-data:/source:ro -v <change-dir>:/backup \
  alpine:3.20 tar -C /source -czf /backup/qwenpaw-data.tgz .
docker run --rm -v qwenpaw-secrets:/source:ro -v <change-dir>:/backup \
  alpine:3.20 tar -C /source -czf /backup/qwenpaw-secrets.tgz .
docker run --rm -v qwenpaw-backups:/source:ro -v <change-dir>:/backup \
  alpine:3.20 tar -C /source -czf /backup/qwenpaw-backups.tgz .
```

Verify archive checksums and copy them to storage with a retention policy.
Do not start the change if the dump list, Nginx test, or volume inventory is
missing.

## 2. Certify migrations before production

The application runs idempotent `create_all()` upgrades at startup. Certify
both paths against the release image before changing production:

1. Start a fresh empty PostgreSQL 16 database and boot the release twice.
2. Restore the latest production dump into an isolated database, boot the
   release twice, and compare row counts and financial sums before and after.
3. Confirm the two new tables, unique indexes, constraints, and immutable
   reconciliation-audit triggers exist.
4. Run the live PostgreSQL billing schema, locking, recovery, reconciliation,
   and rollout-CAS suites.
5. Confirm no migration inserts ledger debits, converts `unbilled` history, or
   changes existing ledger/token rows.

At minimum, compare counts and sums for wallets, lots, ledger entries,
allocations, usage orders/items, invocations, and token logs. Stop on any
unexpected difference. Fresh and production-snapshot upgrades must both be
repeatable without additional changes on the second boot.

## 3. Prepare the release without changing traffic

Build or pull an immutable candidate image and scan it before use.

```bash
docker pull <candidate-image@sha256:digest>
docker image inspect <candidate-image@sha256:digest> \
  > <change-dir>/candidate-image.inspect.json
```

Start one candidate container on an unused loopback port with the production
configuration and volumes/database appropriate to the deployment method. Keep
Nginx pointed at the old container. Check startup recovery, logs, authentication,
and these canaries:

- user billing wallet, ledger, order list/detail, and summary;
- admin order/reconciliation filters and rollout state;
- an idempotent OpenAPI request replay;
- normal agent, expert-team/multi-call, timeout, disconnect, retry, and restart;
- another user's order identifier returns 404;
- no response includes supplier reference/cost/evidence, prompt, content, or a
  credential;
- invalid cursor/timezone/limit inputs fail without an unbounded query;
- historical `unbilled` rows remain absent from financial reports.

Test the candidate upstream directly, then prepare the Nginx upstream change.
Run `nginx -t` before every reload. Keep both upstream definitions available
so rollback is one atomic symlink/config switch plus `nginx -s reload`; never
edit the only production file in place.

## 4. Catalog and wallet readiness

Before shadow traffic, require one published, effective retail catalog whose
rules cover every allowed provider/model/capability/tier. Unknown enforced
provider adapters must remain fail-closed. Verify each quote locks the expected
catalog version and no supplier cost selects or changes a retail rule.

Create every personal wallet through the wallet service. Seed initial credits
only through the immutable ledger primitive (`purchase_grant`,
`promotion_grant`, or `package_grant`) with a unique, deterministic
idempotency key per user and grant campaign. Never update wallet balance
columns or lots with SQL. Re-run the seed and prove ledger/wallet totals do not
change. Record eligible user count, wallet count, seeded count, exclusions,
total credits, and the grant idempotency-key namespace.

Configure optional display-only top-up metadata:

```text
DCLAW_LOW_BALANCE_THRESHOLD=<non-negative credits>
DCLAW_TOP_UP_QR_URL=<approved https image URL or empty>
DCLAW_TOP_UP_INSTRUCTIONS=<approved text or empty>
```

These fields show a QR code/instructions only. They do not collect money or
grant credits.

## 5. Shadow gate

Activate `shadow` through the authenticated admin rollout API. Environment
`DCLAW_BILLING_MODE` is only a bootstrap fallback before durable rollout state
exists. An environment value of `enforced` is deliberately downgraded to
`shadow`: environment configuration cannot bypass the authenticated admin
cutover transaction. `shadow` creates durable quotes/items but never holds or
mutates wallet balances and never writes `billing_cutover_at`.

Observe at least one full peak cycle and all canary scenarios. Recommended
promotion gates (tighten them for local SLOs) are:

- 100% of accepted OpenAPI invocations have one linked order and every model
  call has one stable item;
- zero duplicate item/settlement/ledger events under replay, retry, restart,
  and concurrency tests;
- durable item token totals match official adapter usage exactly where the
  provider is exact, or stay within the adapter's documented tolerance;
- zero supplier secret/cost/prompt/content leakage;
- zero wallet or ledger balance changes attributable to shadow traffic;
- reconciliation rate below the agreed threshold and no unresolved item older
  than the alert window;
- every catalog miss, unsupported adapter, and price mismatch is understood.

Compare shadow durable items with token analytics by invocation/model/time
window. Analytics is comparison data only; it must never drive a debit or
repair a financial item.

## 6. Observe gate

Activate `observe` through the admin API. It calculates whether reservations
would pass and records the estimate, but must not hold or mutate balances and
must not write `billing_cutover_at`.

Measure initial and incremental would-block rates by user, publication,
application, model, and catalog version. Confirm every intended customer has a
wallet/seed, low-balance guidance is visible, and the proposed limits do not
cause an unexplained interruption cohort. Do not promote while any enforced
canary would overdraft, call a supplier after insufficiency, or lack a trusted
provider output cap/evidence adapter.

## 7. Reconciliation and alerts

Page the admin reconciliation queue by stable cursor. It contains only items
whose item state is `reconciling` and billability is `unknown`. Alert on:

- any new item (warning) and any item older than the agreed SLA (page);
- a rising rate by provider/model/adapter version;
- a retained hold approaching credit expiry;
- reconciliation API conflict/error or audit-trigger failure;
- mismatch between item projection, ledger allocation, wallet projection, and
  invocation/order totals.

Manual resolution requires an authenticated admin, `Idempotency-Key`, reason,
final billability, and actual token usage for billable outcomes. The server
derives the actor from authentication, re-prices from the locked catalog,
uses the ledger capture/release primitive, and appends an immutable audit in
one transaction. Operators must never edit an item, wallet, lot, ledger row,
or audit directly.

## 8. Enforced cutover

Freeze unrelated releases. Confirm backups, fresh/upgrade certification,
catalog coverage, wallet seeding, shadow/observe gates, reconciliation staffing,
candidate health, and Nginx rollback are all green.

Send one explicit authenticated admin activation for `enforced`. This is the
only action that may CAS `billing_cutover_at` from NULL. Record the returned UTC
timestamp and actor. Repeating `enforced` must return the original cutover;
switching to `off`, `shadow`, or `observe` never creates or clears it.

After activation:

1. Send a funded one-call canary and verify one hold, evidence-gated capture,
   released excess, one item, one ledger capture, and correct summary debit.
2. Replay the same idempotency key and prove no supplier call or ledger change.
3. Send an unfunded initial canary and prove no supplier contact.
4. Send a multi-call incremental-insufficiency canary and prove it stops before
   the next supplier call while completed steps remain settled.
5. Exercise ambiguous evidence and prove only that item's hold enters the queue.
6. Disconnect an SSE client and verify background finalization.
7. Restart one worker and verify recovery/lease fencing without duplication.

Monitor HTTP errors/latency, provider calls, reservation failures, wallet
projections, ledger rates, reconciliation age/rate, PostgreSQL locks/deadlocks,
startup recovery, and Nginx upstream health continuously through the change
window.

## 9. Low-risk rollback

For a billing-policy incident, first use the authenticated admin API to switch
durable mode to `observe`, `shadow`, or `off`. This stops new wallet mutation;
it does not erase the cutover or reverse legitimate completed ledger entries.
Allow in-flight owners to finalize or reconcile, then investigate.

For an application regression:

1. remove the candidate from Nginx, test config, and reload;
2. route traffic to the exact saved old image digest;
3. keep the current PostgreSQL database and named volumes;
4. verify old-container health and canaries;
5. retain the candidate and logs for diagnosis.

The Task 6 schema is additive and old code should ignore the new rollout/audit
tables. Database-forward compatibility is therefore the preferred rollback:
switching the container/Nginx while keeping the upgraded DB is safer than
restoring a dump, because a restore discards every valid post-backup user,
ledger, invocation, message, and configuration change.

Restore PostgreSQL only when the migration itself corrupted/incompatibly
changed data, the old binary demonstrably cannot run against the upgraded
schema, or incident command explicitly accepts point-in-time data loss. Before
a restore, stop all writers, capture a final forensic dump, record the exact
recovery point, and communicate that all later ledger and non-billing writes
will be lost or must be reconciled. Restore into a new database first, validate
it, then switch the application connection; do not overwrite the only database
copy. A raw `qwenpaw-postgres` volume restore is last resort and requires the
matching PostgreSQL major version and a consistency-certified snapshot.

Do not delete new tables or reset `billing_cutover_at` as a rollback technique.
Do not synthesize refund/reversal ledger rows without a separately approved
financial correction workflow.
