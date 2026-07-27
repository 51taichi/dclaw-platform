# QwenPaw Postgres and Redis SaaS Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` before implementing this plan.

## Goal

Move QwenPaw from the current single-process SQLite plus in-memory runtime state into a SaaS-safe storage shape:

- Postgres owns durable relational data: users, auth state, chats, messages, session states, token logs, MCP connections, expert teams, audit records, and later skill ownership metadata if we choose to move skills out of filesystem manifests.
- Redis owns cross-process runtime coordination: console push messages, approval request metadata, task concurrency counters, task status cache, and later background task queue handoff.
- SQLite and in-memory stores remain as local-development fallbacks until Postgres/Redis rollout is proven by smoke/load tests.
- Do not enable multi-worker or multi-container app replicas until Redis-backed runtime stores are wired and verified.

## Current Findings

The current app is not ready for a direct `DATABASE_URL=postgres://...` switch:

- `src/qwenpaw/app/db.py` exposes a thread-local `sqlite3.Connection`, creates schema at import time, and applies WAL, busy timeout, foreign keys, and indexes.
- `src/qwenpaw/app/runner/repo/sqlite_repo.py` and `src/qwenpaw/app/runner/session_sqlite.py` are hot paths for chat list, chat status, message persistence, and session restore.
- `src/qwenpaw/app/auth.py`, `src/qwenpaw/app/expert_teams.py`, `src/qwenpaw/app/mcp/connections_db.py`, `src/qwenpaw/app/routers/admin_users.py`, `src/qwenpaw/app/routers/audit.py`, `src/qwenpaw/app/routers/workspace.py`, `src/qwenpaw/token_usage/manager.py`, and `src/qwenpaw/app/chat_access.py` call `get_db()` directly.
- `src/qwenpaw/app/console_push_store.py`, `src/qwenpaw/app/approvals/service.py`, and `src/qwenpaw/app/task_limits.py` are process-local and will break under multiple app processes.
- `src/qwenpaw/app/routers/performance.py` already exposes useful diagnostics, so every storage migration step should extend this endpoint rather than adding scattered debug endpoints.

## Architecture

Use a two-layer migration, not a flag-day rewrite.

1. Add storage/runtime configuration and interfaces.
2. Keep SQLite/in-memory as default adapters.
3. Add Postgres and Redis adapters behind the same interfaces.
4. Migrate the hottest durable tables first: chats, messages, session states.
5. Migrate remaining direct `get_db()` callers in waves.
6. Add export/import tooling for existing `/app/working.secret/qwenpaw.db`.
7. After all process-local runtime state is Redis-backed, allow multi-worker deployment as a separate phase.

## Phase 0: Baseline And Safety Gates

### Task 0.1: Capture Current Performance Baseline

Run these before any storage change:

```bash
python scripts/perf/smoke_check.py --base-url http://127.0.0.1:8088
python scripts/perf/load_test.py --base-url http://127.0.0.1:8088 --users 300 --poll-interval 15 --duration 120
curl -s http://127.0.0.1:8088/api/admin/performance/diagnostics | python -m json.tool
```

Save the output locally under:

```text
docs/performance-runs/2026-06-08-before-postgres-redis.md
```

Acceptance:

- Existing SQLite/in-memory baseline is recorded.
- Diagnostics include request metrics, SQLite state, runtime task count, task limits, push message stats, and approval pending count.
- If baseline already fails, fix the failing current behavior before starting Postgres or Redis.

### Task 0.2: Keep Rollout Reversible

Add explicit feature flags:

```text
QWENPAW_DATABASE_BACKEND=sqlite|postgres
QWENPAW_DATABASE_URL=postgresql+psycopg://qwenpaw:password@postgres:5432/qwenpaw
QWENPAW_REDIS_URL=redis://redis:6379/0
QWENPAW_RUNTIME_BACKEND=memory|redis
```

Rules:

- Missing `QWENPAW_DATABASE_BACKEND` means `sqlite`.
- Missing `QWENPAW_RUNTIME_BACKEND` means `memory`.
- Setting `postgres` without `QWENPAW_DATABASE_URL` fails app startup with a clear error.
- Setting `redis` without `QWENPAW_REDIS_URL` fails app startup with a clear error.

## Phase 1: Storage Configuration And Schema Foundation

### Task 1.1: Add Dependencies

Update `/Users/zu/Documents/workes/qwenpaw/pyproject.toml`:

```toml
dependencies = [
    # existing dependencies
    "sqlalchemy>=2.0.41,<3",
    "psycopg[binary]>=3.2.9,<4",
    "redis>=5.2.1,<7",
]

[project.optional-dependencies]
dev = [
    # existing dev dependencies
    "fakeredis>=2.30.1,<3",
]
```

Acceptance:

- `python -m pip install -e ".[dev]"` resolves locally.
- Docker build continues to install dependencies through `uv pip install --no-cache-dir .`.

### Task 1.2: Add Storage Settings Module

Create:

```text
src/qwenpaw/app/storage/settings.py
tests/unit/app/storage/test_settings.py
```

Required behavior:

```python
@dataclass(frozen=True)
class StorageSettings:
    database_backend: Literal["sqlite", "postgres"]
    database_url: str
    sqlite_path: Path
    runtime_backend: Literal["memory", "redis"]
    redis_url: str | None
```

Rules:

- SQLite URL derives from `qwenpaw.app.db.DB_PATH` so existing tests that monkeypatch `DB_PATH` still work.
- `QWENPAW_DATABASE_URL` is accepted for Postgres only.
- `postgres://` is normalized to `postgresql+psycopg://`.
- Secrets are redacted in diagnostics.

Acceptance tests:

- Default settings select SQLite and memory runtime.
- Postgres backend without URL raises `RuntimeError`.
- Redis runtime without URL raises `RuntimeError`.
- Redacted diagnostics never expose username/password.

### Task 1.3: Add SQLAlchemy Engine Factory

Create:

```text
src/qwenpaw/app/storage/engine.py
tests/unit/app/storage/test_engine.py
```

Implement:

```python
def create_engine_from_settings(settings: StorageSettings) -> Engine:
    ...

def db_dialect_name(engine: Engine) -> str:
    ...
```

Rules:

- SQLite engine uses the current `DB_PATH`.
- SQLite connect args include `check_same_thread=False`.
- SQLite connection event applies `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, and `PRAGMA foreign_keys=ON`.
- Postgres engine uses `pool_pre_ping=True`, a bounded pool, and a short connect timeout.

Acceptance:

- SQLite in-memory or temp-file unit tests pass.
- Postgres tests are gated behind `QWENPAW_TEST_POSTGRES_URL` and skipped when absent.

### Task 1.4: Centralize Schema Metadata

Create:

```text
src/qwenpaw/app/storage/schema.py
tests/unit/app/storage/test_schema.py
```

Define SQLAlchemy Core tables equivalent to existing SQLite tables:

- `users`
- `user_connections`
- `capability_registry`
- `user_capabilities`
- `chats`
- `messages`
- `session_states`
- `token_usage_logs`
- `expert_team_templates`
- `expert_team_runs`
- `expert_team_member_runs`

Important details:

- Keep existing column names to avoid API rewrites.
- Use `String` for ids and user ids that are currently mixed as text/integer in code paths.
- Add indexes equivalent to current `init_db()` plus missing `session_states(chat_id)`.
- Use server defaults compatible with Postgres.

Acceptance:

- SQLite `metadata.create_all()` creates all tables and indexes.
- Running schema initialization twice is idempotent.
- Existing `tests/unit/app/test_db_performance_settings.py` still passes.

## Phase 2: Postgres For Chat And Session Hot Paths

### Task 2.1: Add SQLAlchemy Chat Repository

Create:

```text
src/qwenpaw/app/runner/repo/sqlalchemy_repo.py
tests/unit/app/runner/test_chat_repository_parity.py
```

Implement the same `BaseChatRepository` methods as `SqliteChatRepository`:

- `get_chat`
- `get_chat_by_id`
- `upsert_chat`
- `delete_chats`
- `filter_chats`
- `count_messages`
- `get_chat_id_by_session`

Rules:

- Queries must include `agent_id` and `user_id` where current access control expects them.
- `filter_chats` must preserve `ORDER BY updated_at DESC`.
- `get_chat_id_by_session` must remain indexed and direct; no Python-side full scan.

Acceptance:

- Existing SQLite repository tests pass.
- New parity tests run the same behavior against SQLite SQLAlchemy.
- Postgres parity tests run when `QWENPAW_TEST_POSTGRES_URL` is set.

### Task 2.2: Wire Repository Selection

Edit:

```text
src/qwenpaw/app/workspace/service_factories.py
```

Behavior:

```python
if storage_settings().database_backend == "postgres":
    chat_repo = SqlAlchemyChatRepository(agent_id=ws.agent_id, engine=app_engine())
else:
    chat_repo = SqliteChatRepository(agent_id=ws.agent_id)
```

Acceptance:

- Default local app still logs `SqliteChatRepository`.
- Postgres mode logs `SqlAlchemyChatRepository`.
- No request path imports Postgres dependencies unless Postgres backend is selected.

### Task 2.3: Add SQLAlchemy Session Store

Create:

```text
src/qwenpaw/app/runner/session_sqlalchemy.py
tests/unit/app/runner/test_session_store_parity.py
```

Implement the `SqliteSession` behavior with SQLAlchemy:

- Resolve chat id by `(session_id, user_id, channel, agent_id)`.
- Insert fallback chat only when current behavior would do that.
- Persist `messages`.
- Persist `session_states`.
- Load messages in timestamp order.

Important improvement:

- Replace "delete all messages then insert all" with diff-based upsert when message ids are stable.
- If ids are missing or unstable, keep the current overwrite behavior for correctness and log slow writes through the performance logger.

Acceptance:

- Session load/save parity tests pass against SQLite SQLAlchemy.
- Postgres parity tests pass when `QWENPAW_TEST_POSTGRES_URL` is set.
- Long chat save emits slow-write log when over threshold.

### Task 2.4: Wire Session Selection

Edit:

```text
src/qwenpaw/app/runner/runner.py
src/qwenpaw/app/runner/api.py
```

Behavior:

- Default remains `SqliteSession`.
- Postgres backend uses `SqlAlchemySession`.
- Runtime type hints should use `SessionBase` or a local protocol instead of hardcoding `SqliteSession`.

Acceptance:

- Existing chat API tests pass.
- Running a new chat in local default mode persists to SQLite unchanged.
- Postgres mode creates chat, messages, and session states in Postgres.

## Phase 3: Migrate Remaining Durable Tables

### Task 3.1: Move Direct `get_db()` Callers Into Repositories

Create repository modules:

```text
src/qwenpaw/app/storage/repos/auth_repo.py
src/qwenpaw/app/storage/repos/expert_team_repo.py
src/qwenpaw/app/storage/repos/mcp_connections_repo.py
src/qwenpaw/app/storage/repos/token_usage_repo.py
src/qwenpaw/app/storage/repos/audit_repo.py
src/qwenpaw/app/storage/repos/capability_repo.py
```

Edit callers:

```text
src/qwenpaw/app/auth.py
src/qwenpaw/app/expert_teams.py
src/qwenpaw/app/mcp/connections_db.py
src/qwenpaw/token_usage/manager.py
src/qwenpaw/app/routers/admin_users.py
src/qwenpaw/app/routers/audit.py
src/qwenpaw/app/workspace/capabilities_injector.py
src/qwenpaw/app/routers/workspace.py
src/qwenpaw/app/chat_access.py
```

Rules:

- Preserve API behavior and error messages.
- Keep user isolation checks in the same logical locations.
- Repository methods accept `user_id` explicitly; they never infer it from request globals.

Acceptance:

- `rg "get_db\\(" src/qwenpaw/app src/qwenpaw/token_usage` returns only compatibility modules and tests.
- Existing auth, chat access, MCP, expert team, token usage, and workspace tests pass.
- Postgres integration tests cover login, create chat, send message, list chats, expert team run metadata, and token usage logging.

### Task 3.2: Add Migration Script

Create:

```text
scripts/db/migrate_sqlite_to_postgres.py
tests/unit/scripts/test_migrate_sqlite_to_postgres.py
```

CLI:

```bash
python scripts/db/migrate_sqlite_to_postgres.py \
  --sqlite-path /app/working.secret/qwenpaw.db \
  --postgres-url "$QWENPAW_DATABASE_URL" \
  --dry-run

python scripts/db/migrate_sqlite_to_postgres.py \
  --sqlite-path /app/working.secret/qwenpaw.db \
  --postgres-url "$QWENPAW_DATABASE_URL" \
  --execute
```

Required safeguards:

- Dry-run prints table row counts and target connectivity.
- Execute refuses to run when target tables contain rows unless `--allow-non-empty-target` is passed.
- Migration uses transactions per table group.
- Output includes source count, inserted count, skipped count, and error count.
- Passwords are redacted in logs.

Acceptance:

- Dry-run works on a copied production SQLite file.
- Execute works on a disposable local Postgres.
- A second execute run is either refused or idempotent by explicit flag.

## Phase 4: Redis Runtime Stores

### Task 4.1: Add Runtime Store Interfaces

Create:

```text
src/qwenpaw/app/runtime/settings.py
src/qwenpaw/app/runtime/redis_client.py
src/qwenpaw/app/runtime/push_store.py
src/qwenpaw/app/runtime/approval_store.py
src/qwenpaw/app/runtime/task_limit_store.py
tests/unit/app/runtime/
```

Rules:

- Interfaces are async.
- Memory implementations preserve current behavior exactly.
- Redis implementations use namespaced keys:
  - `qwenpaw:push:{session_id}`
  - `qwenpaw:approval:{request_id}`
  - `qwenpaw:approval_by_root:{root_session_id}`
  - `qwenpaw:task_limit:global`
  - `qwenpaw:task_limit:agent:{agent_id}`
  - `qwenpaw:task_limit:user:{user_id}`
- Every Redis key has a TTL appropriate to current memory GC:
  - push messages: 60 seconds
  - approvals: timeout plus 5 minutes
  - task counters: refreshed while held, deleted on release

Acceptance:

- Memory adapter tests match current behavior.
- Redis adapter tests pass with `fakeredis`.
- Redis connection failure at startup fails fast when `QWENPAW_RUNTIME_BACKEND=redis`.

### Task 4.2: Replace Console Push Store

Edit:

```text
src/qwenpaw/app/console_push_store.py
src/qwenpaw/app/routers/console.py
src/qwenpaw/app/crons/manager.py
src/qwenpaw/app/channels/console/channel.py
src/qwenpaw/app/routers/performance.py
```

Behavior:

- Existing import functions `append`, `take`, `take_all`, `get_recent`, and `stats` remain to keep call sites stable.
- Internally dispatch to memory or Redis store based on runtime backend.
- Diagnostics include backend name and Redis ping latency when Redis is enabled.

Acceptance:

- Existing console push tests pass.
- In Redis mode, two app processes can append and consume messages for the same session.

### Task 4.3: Replace Approval Store

Edit:

```text
src/qwenpaw/app/approvals/service.py
src/qwenpaw/app/routers/approval.py
src/qwenpaw/app/runner/control_commands/approval_handler.py
src/qwenpaw/agents/tool_guard_mixin.py
src/qwenpaw/app/routers/performance.py
```

Important design:

- Keep `asyncio.Future` process-local for the tool call that is waiting.
- Store approval metadata in Redis so any web process can list and resolve approvals.
- Resolution publishes to a Redis pub/sub channel `qwenpaw:approval_resolved:{request_id}` so the process holding the future can wake up.
- Memory backend keeps current direct future behavior.

Acceptance:

- Single-process behavior is unchanged.
- Redis mode can create approval in one process and approve from another process.
- Timeout cleanup removes Redis keys and completes local future with timeout.

### Task 4.4: Redis Task Limiter

Edit:

```text
src/qwenpaw/app/task_limits.py
src/qwenpaw/app/routers/console.py
src/qwenpaw/app/routers/skills.py
src/qwenpaw/app/routers/performance.py
```

Behavior:

- Memory limiter remains default.
- Redis limiter acquires global, per-agent, and per-user slots atomically with Lua or Redis transactions.
- Permit release is idempotent.
- Leaked permits expire automatically.

Acceptance:

- Concurrent acquire tests prove limits are enforced.
- Simulated process crash releases capacity by TTL.
- Diagnostics show global, by-agent, and by-user counts in Redis mode.

## Phase 5: Deployment

### Task 5.1: Add Compose Profile For SaaS

Edit:

```text
docker-compose.yml
docs/performance-acceptance.md
```

Add services:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: qwenpaw
      POSTGRES_USER: qwenpaw
      POSTGRES_PASSWORD: ${QWENPAW_POSTGRES_PASSWORD}
    volumes:
      - qwenpaw-postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U qwenpaw -d qwenpaw"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - qwenpaw-redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

App environment:

```yaml
QWENPAW_DATABASE_BACKEND: postgres
QWENPAW_DATABASE_URL: postgresql+psycopg://qwenpaw:${QWENPAW_POSTGRES_PASSWORD}@postgres:5432/qwenpaw
QWENPAW_RUNTIME_BACKEND: redis
QWENPAW_REDIS_URL: redis://redis:6379/0
```

Acceptance:

- Existing single-container Docker path still works.
- SaaS compose path starts Postgres, Redis, and app with health checks.
- App startup fails clearly if Postgres or Redis is unavailable in SaaS mode.

### Task 5.2: Add Aliyun Update Commands

Create:

```text
docs/deployment-postgres-redis.md
```

Include:

- Backup current Docker volumes.
- Pull latest code.
- Build image with existing Aliyun mirror adjustments preserved.
- Start Postgres and Redis volumes.
- Run SQLite to Postgres migration.
- Restart app using Postgres/Redis env vars.
- Run smoke check.
- Run short load check.
- Rollback to SQLite/in-memory by restarting previous app env and keeping existing `dclaw-data`, `dclaw-secrets`, and `dclaw-backups` volumes.

Acceptance:

- The commands are copy-pasteable and do not include real passwords.
- Rollback instructions do not delete volumes.

## Phase 6: Multi-Worker Readiness

Only start this phase after Postgres and Redis mode passes load testing.

### Task 6.1: Multi-Worker Safety Audit

Run:

```bash
rg -n "_pending|_list|asyncio\\.Lock\\(|create_task\\(|app\\.state|global " src/qwenpaw/app src/qwenpaw/agents src/qwenpaw/token_usage
```

Classify every remaining process-local item:

- Safe per-process cache
- Must move to Redis
- Must move to Postgres
- Must remain single-process

Acceptance:

- No approval, push, or task-limit state remains process-local.
- Any process-local cache is bounded and safe to duplicate.

### Task 6.2: Enable Multi-Worker Deployment

Edit:

```text
deploy/config/supervisord.conf.template
docs/deployment-postgres-redis.md
```

Rules:

- Keep default one worker.
- Add documented optional worker count only when runtime backend is Redis.
- Startup refuses multiple workers in memory runtime mode.

Acceptance:

- Two workers pass smoke checks.
- Approval flow works across workers.
- Chat list and chat status stay consistent.
- Load test p95 stays below the target threshold for 100-300 idle users.

## Test Matrix

Run after each phase:

```bash
python -m pytest tests/unit/app/test_db_performance_settings.py -q
python -m pytest tests/unit/app/test_chat_access.py -q
python -m pytest tests/unit/app/runner -q
python -m pytest tests/unit/app/storage -q
python -m pytest tests/unit/app/runtime -q
python -m pytest tests/unit/scripts -q
```

Frontend and integration checks:

```bash
cd console && npm run test:run -- src/pages/Chat
python scripts/perf/smoke_check.py --base-url http://127.0.0.1:8088
python scripts/perf/load_test.py --base-url http://127.0.0.1:8088 --users 300 --poll-interval 15 --duration 120
```

Postgres optional checks:

```bash
QWENPAW_TEST_POSTGRES_URL=postgresql+psycopg://qwenpaw:test@127.0.0.1:5432/qwenpaw_test \
python -m pytest tests/unit/app/storage tests/unit/app/runner -q
```

Redis optional checks:

```bash
QWENPAW_RUNTIME_BACKEND=redis \
QWENPAW_REDIS_URL=redis://127.0.0.1:6379/15 \
python -m pytest tests/unit/app/runtime -q
```

## Rollout Gates

Gate 1, before merging code:

- Default SQLite/in-memory mode is unchanged.
- New Postgres/Redis code is behind env flags.
- Unit tests pass.

Gate 2, before enabling Postgres on Aliyun:

- SQLite backup exists.
- Migration dry-run row counts match expectations.
- Postgres mode passes smoke check.

Gate 3, before enabling Redis on Aliyun:

- Memory runtime remains available for rollback.
- Redis mode passes push message, approval, and task-limit tests.

Gate 4, before multi-worker:

- Runtime backend is Redis.
- Diagnostics show no process-local pending approvals or push messages as authoritative state.
- Load test with 300 idle users and 20 concurrent tasks meets acceptance thresholds.

## First Implementation Slice

Start with the smallest valuable slice:

1. Add `storage/settings.py`, `storage/engine.py`, and tests.
2. Extend `/api/admin/performance/diagnostics` with storage/runtime backend diagnostics.
3. Add `storage/schema.py` and idempotent schema tests.
4. Add SQLAlchemy chat repository parity tests without wiring Postgres as default.

Stop after this slice and run:

```bash
python -m pytest tests/unit/app/storage tests/unit/app/test_db_performance_settings.py -q
python -m pytest tests/unit/app/runner/test_chat_repository_parity.py -q
python -m py_compile src/qwenpaw/app/storage/settings.py src/qwenpaw/app/storage/engine.py src/qwenpaw/app/storage/schema.py
```

This creates a safe foundation without touching live request behavior.
