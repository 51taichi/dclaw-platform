# Task 3 Report: Incremental OpenAPI model-call settlement

## Delivered

- `UsageService.reserve_model_call()` records one stable item per call and,
  before supplier execution in enforced mode, appends a per-item hold against
  the invocation's locked wallet and catalog.
- `settle_model_call()` requires a supplier reference and evidence for a
  billable outcome, captures actual locked-catalog retail usage with the
  repository's atomic remainder release, releases not-billable holds, and
  leaves unknown outcomes reconciling with their item hold intact.
- Item replay is idempotent only for the same reservation or settlement
  payload; item-key drift raises a controlled usage-order conflict.
- Order and invocation amounts plus token summary are rebuilt synchronously
  from durable items and hold allocations, not the analytics queue.  New item
  snapshots include OpenAPI source, invocation source id, item key, catalog
  id, reservation, and immutable retail quote.
- `observe` is accepted as a no-wallet-mutation billing mode, matching the
  OpenAPI coordinator's public mode contract.
- Billable zero-actual usage releases its entire hold while retaining the
  billable/captured evidence state; a reconciling item can later settle when
  supplier evidence arrives.  SQLite same-item reservation races reload the
  durable item and replay it, and signup trials require an explicit allowed
  tier policy.

## RED → GREEN evidence

- Initial RED: the new Task 3 test module failed collection because
  `ReserveModelCall` did not exist.
- Additional RED: an observe-mode invocation raised `ValueError` from the old
  usage-mode parser.  The parser now accepts `off|shadow|observe|enforced`.
- SQLite focused command: `41 passed, 4 skipped` when PostgreSQL is not
  configured.
- Live PostgreSQL 16.14 command:

  ```text
  QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
    .venv/bin/python -m pytest \
    tests/unit/app/billing/test_open_api_billing.py \
    tests/unit/app/storage/repos/test_billing_repo.py \
    tests/integration/test_open_api_billing_postgres.py -q
  127 passed
  ```

  PostgreSQL tests create a UUID-isolated schema and always drop it in the
  fixture finalizer.  The new race test proves capture and release cannot both
  settle one item.

- `python -m compileall -q` for changed modules and `git diff --check` pass.

## Coverage

The new behavior is tested for multi-call incremental reservation, mixed
billability, insufficient-credit preflight at the service boundary, partial
capture/excess release, reservation and settlement replay/drift, locked catalog
pricing, invocation budget, trial tier fail-closed behavior, observe mode, and
SQLite same-item and PostgreSQL capture-vs-release contention.  Existing repository regression
coverage exercises expiry and exact original-lot partial-allocation behavior.

## Scope

No router or model-wrapper integration was changed; Task 4/5 consume the new
service commands at their respective boundaries.
