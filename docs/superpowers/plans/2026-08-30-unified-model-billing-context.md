# Unified Model Billing Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce wallet-backed, customer-visible credit billing for every user-triggered model call across client experts, expert teams, OpenAPI, automations, schedules, and external channels.

**Architecture:** Entry points create a durable usage order and install a general request-scoped billing context; the shared model meter remains the only component allowed to reserve and settle individual calls. Existing OpenAPI invocation fencing stays intact, while non-OpenAPI requests use a durable general execution row with the same owner/generation/lease principles. Server and client changes ship as separate commits and are verified together against SQLite and PostgreSQL.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, PostgreSQL 16, SQLite, ContextVar, pytest, React, TypeScript, Ant Design, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-30-unified-model-billing-context-design.md`

## Global Constraints

- Production behavior is immediately `enforced`; existing zero-balance users receive no free allowance.
- Every user-triggered model call must have an authenticated payer or fail before supplier contact.
- OpenAPI must retain its existing invocation fencing, replay, recovery, and terminal-snapshot behavior.
- The shared model meter is the only layer that reserves, captures, or releases per-call credits.
- A pre-contact failure releases the hold; verified usage is charged; an uncertain post-contact result remains reconciling.
- Customer DTOs must not expose database IDs, API-key IDs, idempotency keys, supplier references, evidence, prompts, skills, source files, or sealed assets.
- Expert-team continuation reuses the original run and never repeats completed or charged calls.
- All financial mutations are transactional and use stable idempotency keys across retries, restarts, and workers.

---

### Task 1: General Billing Execution Schema and Repository

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/db.py`
- Create: `src/qwenpaw/app/storage/repos/billing_execution_repo.py`
- Test: `tests/unit/app/storage/test_billing_schema.py`
- Test: `tests/unit/app/storage/repos/test_billing_execution_repo.py`
- Test: `tests/integration/test_billing_schema_postgres.py`

**Interfaces:**
- Produces: `BillingExecutionFence(owner_token: str, generation: int)`.
- Produces: `BillingExecutionRepository.create_or_replay(command) -> BillingExecutionRecord`.
- Produces: `claim(execution_id, lease_seconds) -> BillingExecutionFence | None`, `renew(execution_id, fence, lease_seconds) -> bool`, and `finalize(execution_id, fence, state, error_code) -> bool`.
- Produces: a `billing_executions` table linked one-to-one to `billing_usage_orders` with source, payer, state, owner token, generation, lease expiry, resume metadata, and immutable request hash.

- [ ] **Step 1: Write fresh and legacy schema failures**

Add tests asserting that two calls to schema bootstrap create and preserve:

```python
assert columns("billing_executions") >= {
    "id", "usage_order_id", "payer_user_id", "source_type",
    "source_id", "request_sha256", "state", "owner_token",
    "fence_generation", "lease_expires_at", "resume_state_json",
    "exemption_actor", "exemption_reason", "error_code", "created_at",
    "updated_at",
}
assert unique_columns("billing_executions") == {"usage_order_id"}
```

Cover SQLite upgrade from a database without the table and PostgreSQL bootstrap twice without unconditional type rewrites.

- [ ] **Step 2: Run schema tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/app/storage/test_billing_schema.py \
  tests/integration/test_billing_schema_postgres.py -q
```

Expected: failures because `billing_executions` does not exist.

- [ ] **Step 3: Add the table and idempotent bootstrap**

Define the SQLAlchemy table with `state` constrained to `accepted`, `running`, `paused_insufficient_balance`, `succeeded`, `failed`, `cancelled`, or `reconciling`. Add indexes for `(payer_user_id, created_at)`, `(source_type, source_id)`, and stale lease recovery. Mirror the table in the legacy SQLite bootstrap without request-time `create_all` calls.

- [ ] **Step 4: Write repository concurrency tests**

Test same-key replay, request-hash drift, eight concurrent claims with one winner, lease renewal, expired takeover with generation increment, and stale-owner finalize rejection. Assert database time controls expiry by passing a deliberately skewed application clock.

- [ ] **Step 5: Implement the repository**

Use DB-clock comparisons and owner-token plus generation predicates for every state mutation. Return immutable records; never accept caller-supplied `now`. Follow the existing OpenAPI lock order: usage order before execution row whenever both are locked.

- [ ] **Step 6: Run SQLite and PostgreSQL repository tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/app/storage/repos/test_billing_execution_repo.py \
  tests/unit/app/storage/test_billing_schema.py -q
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest \
  tests/integration/test_billing_schema_postgres.py -q
```

Expected: all pass and temporary PostgreSQL schemas are removed.

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/db.py \
  src/qwenpaw/app/storage/repos/billing_execution_repo.py \
  tests/unit/app/storage/test_billing_schema.py \
  tests/unit/app/storage/repos/test_billing_execution_repo.py \
  tests/integration/test_billing_schema_postgres.py
git commit -m "feat: persist general billing executions"
```

### Task 2: General Session Coordinator and Context

**Files:**
- Create: `src/qwenpaw/app/billing/context.py`
- Create: `src/qwenpaw/app/billing/coordinator.py`
- Modify: `src/qwenpaw/app/agent_context.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Test: `tests/unit/app/billing/test_billing_context.py`
- Test: `tests/unit/app/billing/test_billing_coordinator.py`
- Test: `tests/unit/app/open_api/test_billing_context.py`

**Interfaces:**
- Produces: `BillingSource(type: str, id: str, expert_id: str | None, expert_team_run_id: str | None)`.
- Produces: `BillingSession(execution_id, usage_order_id, wallet_id, payer_user_id, catalog_version, source, mode)`.
- Produces: `BillingExecutionContext(session: BillingSession, fence: BillingExecutionFence)`.
- Produces: `billing_context(session, fence, meter)` context manager.
- Consumes: Task 1 repository claim and fencing APIs.

- [ ] **Step 1: Write context isolation and coordinator RED tests**

Cover async child-task inheritance, sibling isolation, `finally` cleanup, same business-key replay, payload drift, wallet ownership, locked catalog version, and missing payer/catalog failures. Assert mode is always `enforced` for general user entry points.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/billing/test_billing_context.py \
  tests/unit/app/billing/test_billing_coordinator.py -q
```

Expected: import failures for the new context and coordinator.

- [ ] **Step 3: Implement immutable context types and coordinator**

Create the wallet, locked catalog, usage order, and execution row in one transaction. Use a namespaced business key:

```python
business_key = f"billing:{source.type}:{source.id}:{request_key}"
```

Store only a SHA-256 request fingerprint and safe source snapshot; never store prompts. Install both the context and request meter with ContextVar tokens and reset both in `finally`.

- [ ] **Step 4: Preserve OpenAPI compatibility**

Make the shared context reader accept `OpenApiBillingExecutionContext` and the new `BillingExecutionContext`. Keep `open_api_billing_context()` and its public types unchanged so existing replay and recovery tests remain valid.

- [ ] **Step 5: Run context, coordinator, and OpenAPI regression tests**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/billing/test_billing_context.py \
  tests/unit/app/billing/test_billing_coordinator.py \
  tests/unit/app/open_api/test_billing_context.py \
  tests/unit/app/billing/test_open_api_billing.py -q
```

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/billing/context.py \
  src/qwenpaw/app/billing/coordinator.py \
  src/qwenpaw/app/agent_context.py src/qwenpaw/app/open_api/runtime.py \
  tests/unit/app/billing/test_billing_context.py \
  tests/unit/app/billing/test_billing_coordinator.py \
  tests/unit/app/open_api/test_billing_context.py
git commit -m "feat: create general billing contexts"
```

### Task 3: Generalize the Model Meter Without Double Charging OpenAPI

**Files:**
- Modify: `src/qwenpaw/app/billing/model_meter.py`
- Modify: `src/qwenpaw/app/billing/usage.py`
- Modify: `src/qwenpaw/token_usage/model_wrapper.py`
- Modify: `src/qwenpaw/agents/model_factory.py`
- Test: `tests/unit/app/billing/test_model_meter.py`
- Test: `tests/unit/agents/test_model_factory_billing_adapters.py`
- Test: `tests/integration/test_billing_repo_postgres.py`

**Interfaces:**
- Consumes: `BillingExecutionContext` and existing `OpenApiBillingExecutionContext`.
- Produces: `MissingBillingContextError`, `BillingPayerUnavailableError`, and the existing `InsufficientUsageCreditsError` before provider contact.
- Produces: one stable item key per execution and model-call UUID.

- [ ] **Step 1: Write meter RED tests**

Add tests for general-context reserve/contact/settle, zero balance before provider contact, exact-boundary balance, missing context fail-closed, explicit audited system exemption, OpenAPI single charge, verified usage, known pre-contact failure, unknown post-contact outcome, retry replay, and drift rejection.

- [ ] **Step 2: Run meter tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/billing/test_model_meter.py \
  tests/unit/agents/test_model_factory_billing_adapters.py -q
```

- [ ] **Step 3: Generalize the usage execution guard**

Replace OpenAPI-only command fields with a discriminated execution guard:

```python
@dataclass(frozen=True)
class UsageExecutionGuard:
    kind: Literal["open_api", "general"]
    execution_id: str
    owner_token: str
    generation: int
```

For `open_api`, validate against `open_api_invocations`; for `general`, validate against `billing_executions`. Perform the guard as the first write inside the same reserve/settle transaction and retain order-before-execution lock order.

- [ ] **Step 4: Make user calls fail closed**

Change `BillingModelMeter.before_call()` so a model call identified as user-originated without either valid billing context raises `MissingBillingContextError`. Keep local bootstrap/model-management work usable only through an explicit `SystemBillingExemption(reason, actor)` context. Installing that context must first append a terminal `billing_executions` audit row with `source_type=system_exemption`, the authenticated actor, and the allowlisted reason; no wallet or usage item is created.

- [ ] **Step 5: Preserve wrapper lifecycle guarantees**

Run all existing stream tests covering unstarted close, partial close, cancellation, retry, distinct async iterators, supplier-reference sidecars, and provider-native token caps. Confirm financial finalization still occurs exactly once and analytics queue failure remains isolated.

- [ ] **Step 6: Run focused and live PostgreSQL tests**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/billing/test_model_meter.py \
  tests/unit/agents/test_model_factory_billing_adapters.py \
  tests/unit/token_usage -q
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest tests/integration/test_billing_repo_postgres.py -q
```

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/billing/model_meter.py \
  src/qwenpaw/app/billing/usage.py \
  src/qwenpaw/token_usage/model_wrapper.py \
  src/qwenpaw/agents/model_factory.py \
  tests/unit/app/billing/test_model_meter.py \
  tests/unit/agents/test_model_factory_billing_adapters.py \
  tests/integration/test_billing_repo_postgres.py
git commit -m "feat: meter every user model call"
```

### Task 4: Client and Mobile Expert Entry Points

**Files:**
- Modify: `src/qwenpaw/app/routers/console.py`
- Modify: `src/qwenpaw/app/routers/mobile.py`
- Create: `src/qwenpaw/app/billing/entrypoint.py`
- Test: `tests/integration/test_console_billing_flow.py`
- Test: `tests/unit/app/test_mobile_router.py`
- Test: `tests/unit/app/test_console_chat_headers.py`

**Interfaces:**
- Produces: `prepare_user_billing_execution(payer_user_id, source, request_key, request_fingerprint) -> PreparedBillingExecution`.
- Produces: safe HTTP/SSE error code `INSUFFICIENT_CREDITS` with `available_credits`, `required_credits`, and `top_up_path`.
- Consumes: Tasks 1–3 context, coordinator, and meter.

- [ ] **Step 1: Write real FastAPI RED tests**

Use authenticated TestClient requests and SQLite durable storage. Assert a zero-credit console/mobile expert request returns the controlled error before fake-provider invocation; funded calls invoke once, create one order/item, charge once, and expose source `client` or `mobile`. Cover disconnect and reconnect without duplicate charging.

- [ ] **Step 2: Run entry-point tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/integration/test_console_billing_flow.py \
  tests/unit/app/test_mobile_router.py \
  tests/unit/app/test_console_chat_headers.py -q
```

- [ ] **Step 3: Install context around the TaskTracker producer**

Create and claim billing execution before `attach_or_start`. The TaskTracker-owned producer, not the HTTP subscriber generator, owns the context so browser disconnects do not end billing. Reconnect performs attach-only and never creates a new order or supplier call.

- [ ] **Step 4: Return durable safe outcomes**

Emit an SSE billing error before stream closure and return the same safe fields for non-streaming/mobile requests. Never include supplier error bodies or internal execution identifiers.

- [ ] **Step 5: Run focused tests**

Run the command from Step 2. Expected: all pass with provider call count zero for insufficient balance and one for a funded replay sequence.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/routers/console.py src/qwenpaw/app/routers/mobile.py \
  src/qwenpaw/app/billing/entrypoint.py \
  tests/integration/test_console_billing_flow.py \
  tests/unit/app/test_mobile_router.py \
  tests/unit/app/test_console_chat_headers.py
git commit -m "feat: bill client expert conversations"
```

### Task 5: Expert-Team Pause and Durable Continuation

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/storage/repos/expert_team_repo.py`
- Modify: `src/qwenpaw/app/expert_teams.py`
- Modify: `src/qwenpaw/app/routers/console.py`
- Test: `tests/unit/app/storage/repos/test_expert_team_repo.py`
- Test: `tests/unit/app/test_expert_teams.py`
- Test: `tests/integration/test_expert_team_billing_flow.py`

**Interfaces:**
- Produces: expert-team run state `paused_insufficient_balance`.
- Produces: durable fields `next_member_key`, `required_credits`, and `billing_usage_order_id`.
- Produces: `resume_expert_team_run(run_id, payer_user_id) -> ExpertTeamRun`.

- [ ] **Step 1: Write schema and orchestration RED tests**

Test a three-member run where the first call succeeds and the second reserve fails. Assert first result/charge persists, later supplier calls remain zero, run pauses with the second member as next, and repeated pause events do not mutate the ledger.

- [ ] **Step 2: Write continuation RED tests**

After a wallet grant, test both an explicit resume endpoint and a console “继续” message. Assert they reuse the original run/order, skip completed members, execute remaining calls once, and produce one terminal completion event. A “继续” message on a non-paused task remains ordinary user content.

- [ ] **Step 3: Run tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/storage/repos/test_expert_team_repo.py \
  tests/unit/app/test_expert_teams.py \
  tests/integration/test_expert_team_billing_flow.py -q
```

- [ ] **Step 4: Implement pause/resume persistence**

Persist pause state and next member in the same transition that handles the insufficient reserve. Resume uses a compare-and-set from `paused_insufficient_balance` to `running`, validates the same payer, and retains stable member item keys:

```python
item_key = f"expert-team:{run.id}:member:{member.key}:call:{call_index}"
```

- [ ] **Step 5: Implement both continuation adapters**

Add `POST /api/user/expert-teams/runs/{run_id}/continue` and narrowly interpret “继续” only when the current chat's latest durable team run is paused for insufficient balance.

- [ ] **Step 6: Run focused tests and PostgreSQL concurrency replay**

Run the command from Step 3 plus the PostgreSQL expert-team integration test. Assert two simultaneous resume requests have one winner.

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/storage/schema.py \
  src/qwenpaw/app/storage/repos/expert_team_repo.py \
  src/qwenpaw/app/expert_teams.py src/qwenpaw/app/routers/console.py \
  tests/unit/app/storage/repos/test_expert_team_repo.py \
  tests/unit/app/test_expert_teams.py \
  tests/integration/test_expert_team_billing_flow.py
git commit -m "feat: resume billed expert team runs"
```

### Task 6: Automations, Schedules, and External Channels

**Files:**
- Modify: `src/qwenpaw/app/channels/base.py`
- Modify: `src/qwenpaw/app/channels/manager.py`
- Modify: `src/qwenpaw/app/crons/manager.py`
- Create: `src/qwenpaw/app/billing/payer.py`
- Test: `tests/unit/channels/test_base_core.py`
- Test: `tests/unit/app/test_cron_user_access.py`
- Create: `tests/integration/test_background_channel_billing.py`

**Interfaces:**
- Produces: `resolve_channel_payer(channel, external_user_id, channel_meta) -> str`.
- Produces: `resolve_job_payer(job) -> str` using the durable job owner, never the delivery target alone.
- Consumes: Task 4 `prepare_user_billing_execution`.

- [ ] **Step 1: Write payer-resolution RED tests**

Cover a bound WeChat/DingTalk identity, an unbound channel identity, an owned scheduled job, a deleted owner, and a delivery target different from the job owner. Assert ambiguous/unbound callers fail before provider invocation.

- [ ] **Step 2: Write background execution RED tests**

Test zero-balance scheduled/channel calls, funded calls, retry after process restart, and analytics queue failure. Assert controlled channel replies and cron failure state contain no supplier credentials.

- [ ] **Step 3: Run tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/channels/test_base_core.py \
  tests/unit/app/test_cron_user_access.py \
  tests/integration/test_background_channel_billing.py -q
```

- [ ] **Step 4: Implement payer resolver and producer-owned contexts**

Resolve channel bindings from durable authenticated mappings. Resolve cron payer from the persisted creator/owner field. Install billing inside the TaskTracker or cron background task so HTTP/request lifetimes cannot clear it early.

- [ ] **Step 5: Add safe insufficient-balance delivery**

Channels send a localized “积分不足，请充值后重试” response with the top-up URL. Scheduled jobs persist `failed` with code `INSUFFICIENT_CREDITS`; they do not loop or contact the provider until the next scheduled/manual attempt.

- [ ] **Step 6: Run channel contracts and focused tests**

```bash
.venv/bin/python -m pytest \
  tests/unit/channels tests/contract/channels \
  tests/unit/app/test_cron_user_access.py \
  tests/integration/test_background_channel_billing.py -q
```

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/channels/base.py src/qwenpaw/app/channels/manager.py \
  src/qwenpaw/app/crons/manager.py src/qwenpaw/app/billing/payer.py \
  tests/unit/channels/test_base_core.py \
  tests/unit/app/test_cron_user_access.py \
  tests/integration/test_background_channel_billing.py
git commit -m "feat: bill channel and scheduled model calls"
```

### Task 7: Customer Usage Reporting for Every Source

**Files:**
- Modify: `src/qwenpaw/app/billing/reporting.py`
- Modify: `src/qwenpaw/app/routers/billing.py`
- Test: `tests/unit/app/billing/test_billing_reporting.py`
- Test: `tests/unit/app/routers/test_billing.py`

**Interfaces:**
- Produces: source filters for `client`, `mobile`, `openapi`, `expert_team`, `automation`, `schedule`, and `channel`.
- Produces: public order fields `source`, `expert`, `expert_team`, `call_count`, token totals, held/captured/released/reconciling credits, and status.
- Produces: public item fields `call_sequence`, `expert_role`, `model`, `provider`, `capability`, token totals, charged credits, status, and catalog version.

- [ ] **Step 1: Write reporting RED tests**

Build mixed-source fixtures and assert owner isolation, filters, bounded UTC summaries, constant query counts, expert-team grouping, pause state, and exact customer allowlists. Explicitly assert forbidden internal fields are absent at every nesting level.

- [ ] **Step 2: Run reporting tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/billing/test_billing_reporting.py \
  tests/unit/app/routers/test_billing.py -q
```

- [ ] **Step 3: Extend batched reporting queries**

Reuse the existing eligible-owner/window CTE and batched item/ledger aggregation. Add safe joins for expert/team display data without per-order queries. Preserve opaque pagination cursors and the maximum 366-day summary window.

- [ ] **Step 4: Add route filters and DTOs**

Extend existing user usage list/detail/summary endpoints rather than creating duplicate APIs. Validate source/status values and continue returning 404 for another user's order.

- [ ] **Step 5: Run focused and PostgreSQL timezone tests**

Run the command from Step 2 and the existing PostgreSQL reporting suite under a non-UTC session timezone.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/billing/reporting.py \
  src/qwenpaw/app/routers/billing.py \
  tests/unit/app/billing/test_billing_reporting.py \
  tests/unit/app/routers/test_billing.py
git commit -m "feat: report billing across model entry points"
```

### Task 8: Client Wallet Details, Billing Errors, and Team Continuation

**Files (dclaw-client repository):**
- Modify: `console/src/api/types/billing.ts`
- Modify: `console/src/api/modules/billing.ts`
- Modify: `console/src/pages/Wallet/index.tsx`
- Modify: `console/src/pages/Wallet/WalletPage.test.tsx`
- Modify: `console/src/pages/Chat/index.tsx`
- Create: `console/src/features/billing/BillingFailureAlert.tsx`
- Create: `console/src/features/billing/BillingFailureAlert.test.tsx`
- Modify: `console/src/locales/zh-CN.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Consumes: Task 4 `INSUFFICIENT_CREDITS` safe fields.
- Consumes: Task 5 expert-team paused state and continue endpoint.
- Consumes: Task 7 public order/item DTOs.
- Produces: explicit balance error, top-up link, usage detail drawer, and “充值后继续” action.

- [ ] **Step 1: Write client RED tests**

Test a chat SSE insufficient-balance event, a paused expert-team event, continue success/failure, mixed-source usage filters, per-call detail rendering, reconciling status, and forbidden-field absence from displayed data.

- [ ] **Step 2: Run Vitest and confirm RED**

From `/Users/moxi/Desktop/codex space/dclaw-client/console` run:

```bash
npm test -- --run \
  src/pages/Wallet/WalletPage.test.tsx \
  src/features/billing/BillingFailureAlert.test.tsx
```

- [ ] **Step 3: Extend typed API contracts**

Add discriminated usage sources and billing status types. Add:

```typescript
continueExpertTeamRun: (runId: string) =>
  request<ExpertTeamRun>(`/expert-teams/runs/${runId}/continue`, {
    method: "POST",
  })
```

Do not add internal IDs to TypeScript public DTOs.

- [ ] **Step 4: Implement wallet detail and filters**

Render order totals and expandable per-call rows for source, expert/team, model/provider, input/output tokens, charged credits, state, and catalog version. Include daily/monthly summaries and reconciling status.

- [ ] **Step 5: Implement chat billing states**

Render an explicit insufficient-balance alert instead of an empty assistant response. For paused team runs, retain completed outputs and show top-up plus continue controls. Disable repeated continue submission while one request is pending.

- [ ] **Step 6: Run client tests, typecheck, and production build**

```bash
npm test -- --run
npm run typecheck
NODE_OPTIONS=--max-old-space-size=4096 npm run build
```

- [ ] **Step 7: Commit in dclaw-client**

```bash
git add console/src/api/types/billing.ts console/src/api/modules/billing.ts \
  console/src/pages/Wallet console/src/pages/Chat/index.tsx \
  console/src/features/billing/BillingFailureAlert.tsx \
  console/src/features/billing/BillingFailureAlert.test.tsx \
  console/src/locales/zh-CN.json console/src/locales/en.json
git commit -m "feat: show model billing and team continuation"
```

### Task 9: Recovery, Full Verification, and Release Evidence

**Files:**
- Modify: `src/qwenpaw/app/_app.py`
- Create: `src/qwenpaw/app/billing/recovery.py`
- Test: `tests/integration/test_general_billing_recovery.py`
- Modify: `docs/operations/open-api-billing-rollout.md`

**Interfaces:**
- Produces: `recover_general_billing() -> int`, called after durable schema bootstrap and before accepting traffic.
- Consumes: Tasks 1–7 durable execution, item, order, and ledger state.

- [ ] **Step 1: Write recovery RED tests**

Cover pre-contact held work, provider-contacted work, fully resolved items with stale running execution, paused expert-team runs, active unexpired owners, expired takeover, two concurrent recovery workers, and repeated recovery with no additional ledger entries.

- [ ] **Step 2: Run recovery tests and confirm RED**

```bash
.venv/bin/python -m pytest tests/integration/test_general_billing_recovery.py -q
```

- [ ] **Step 3: Implement startup recovery**

Use atomic stale-owner takeover. Release known pre-contact holds, retain contacted unknown holds as reconciling, project resolved orders, repair stale execution states, and preserve paused expert-team continuation. In enforced mode, a recovery exception prevents application readiness.

- [ ] **Step 4: Run server focused and live PostgreSQL suites**

```bash
.venv/bin/python -m pytest \
  tests/unit/app/billing \
  tests/unit/app/storage/repos/test_billing_repo.py \
  tests/unit/app/storage/repos/test_billing_execution_repo.py \
  tests/integration/test_console_billing_flow.py \
  tests/integration/test_expert_team_billing_flow.py \
  tests/integration/test_background_channel_billing.py \
  tests/integration/test_general_billing_recovery.py -q
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest tests/integration -q
```

- [ ] **Step 5: Run static verification**

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m mypy src/qwenpaw/app/billing src/qwenpaw/app/storage/repos
git diff --check
```

Run applicable pre-commit Python hooks. If the repository's known Prettier npm bootstrap error recurs without TypeScript changes in the server repository, record it separately and do not describe the aggregate hook as passing.

- [ ] **Step 6: Run full server and client suites**

```bash
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
  .venv/bin/python -m pytest -q
cd '/Users/moxi/Desktop/codex space/dclaw-client/console'
npm test -- --run
npm run typecheck
NODE_OPTIONS=--max-old-space-size=4096 npm run build
```

Classify every failure with a focused reproduction. Do not silently ignore a failure on a billing, console, expert-team, cron, channel, wallet, or reporting path.

- [ ] **Step 7: Update the rollout runbook**

Document the immediate-enforced effect, zero-balance behavior, customer top-up/continue validation, usage-detail validation, backup, combined-image revision labels, health gates, and rollback. Use the existing digest-pinned combined-image deployment workflow.

- [ ] **Step 8: Commit server recovery and operations changes**

```bash
git add src/qwenpaw/app/_app.py src/qwenpaw/app/billing/recovery.py \
  tests/integration/test_general_billing_recovery.py \
  docs/operations/open-api-billing-rollout.md
git commit -m "feat: recover general billing executions"
```

- [ ] **Step 9: Request final code review before merging**

Review schema upgrades, wallet invariants, multi-worker fencing, every entry-point payer path, OpenAPI non-regression, customer redaction, expert-team continuation, and production rollback. Resolve all Critical and Important findings, rerun the affected focused suites, and record exact final SHAs for both repositories.
