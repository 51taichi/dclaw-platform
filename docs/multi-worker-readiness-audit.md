# QwenPaw Multi-Worker Readiness Audit

Audit command:

```bash
rg -n "_pending|_list|asyncio\\.Lock\\(|create_task\\(|app\\.state|global " \
  src/qwenpaw/app src/qwenpaw/agents src/qwenpaw/token_usage
```

Date: 2026-06-08

Updated: 2026-06-11

## 2026-06-11 SaaS Stability Pass

The current production target remains one app container backed by Postgres and
Redis. This pass reduces single-worker load and makes the next multi-worker
decision safer:

- Chat list reads no longer start unloaded workspaces and no longer run ghost
  chat cleanup writes on the hot read path.
- Task stream replay buffers are bounded by event count and bytes via
  `QWENPAW_TASK_STREAM_MAX_BUFFER_EVENTS` and
  `QWENPAW_TASK_STREAM_MAX_BUFFER_BYTES`.
- Performance diagnostics now expose per-loaded-agent task stream buffer
  metrics and Redis task limiter rejected/expired counters.
- Session message persistence uses dialect-native bulk upsert for SQLite and
  Postgres instead of per-message select/update/insert loops.
- AIGC Studio list endpoints support scoped pagination/filtering for jobs and
  assets, reducing repeated full JSON scans for active canvases.

These changes improve single-container stability and observability. They do not
make non-sticky multi-worker execution safe by themselves.

## Ready In Redis Runtime

These areas no longer rely on process-local state for cross-process behavior
when `QWENPAW_RUNTIME_BACKEND=redis`:

- Console push messages:
  - `src/qwenpaw/app/console_push_store.py`
  - `src/qwenpaw/app/runtime/push_store.py`
  - Memory mode remains a local fallback; Redis mode shares messages by session.
- Tool approval metadata and decisions:
  - `src/qwenpaw/app/approvals/service.py`
  - `src/qwenpaw/app/runtime/approval_store.py`
  - Metadata is shared in Redis.
  - Approve/deny from another process publishes a decision to
    `qwenpaw:approval_resolved:{request_id}`-style namespaced channels.
  - The local `asyncio.Future` remains process-local by design because it is the
    live tool-call wait primitive; Redis pub/sub wakes the process holding it.
- Task concurrency limits:
  - `src/qwenpaw/app/task_limits.py`
  - Redis mode enforces global, per-agent, and per-user slots across processes.
  - Permit keys have TTLs and are refreshed while held.

## Safe Per-Process Caches Or Managers

These are acceptable to duplicate per worker, assuming the durable data and
runtime coordination stores above are enabled:

- `app.state.provider_manager`
- `app.state.local_model_manager`
- `app.state.plugin_loader` / `plugin_registry`
- Request performance metric ring buffer in `src/qwenpaw/app/performance.py`
- Built-in channel registry cache in `src/qwenpaw/app/channels/registry.py`
- Docker/container-local browser, media, and channel connection handles.

They are caches, local IO/session handles, or diagnostics. They should stay
bounded and should not be used as durable state.

## Must Stay Single-Worker Until Routed Or Externalized

These are live execution surfaces. Running multiple workers is risky unless
requests for a live session are sticky to the same worker or the state is moved:

- `src/qwenpaw/app/multi_agent_manager.py`
  - Loaded workspace instances are process-local.
  - `_pending_starts` coordinates startup only inside one process.
- `src/qwenpaw/app/runner/task_tracker.py`
  - Streaming queues and live run tasks are process-local.
  - Replay buffers are now bounded and visible in diagnostics, but reconnects
    still need to hit the same process unless task streaming is externalized.
  - Reconnects must hit the same process unless task streaming is moved to
    Redis/worker queues.
- Channel clients and websocket/gateway tasks:
  - Telegram, WeCom, DingTalk, Matrix, Mattermost, Discord, OneBot, Feishu,
    Xiaoyi, Voice, and unified queue managers hold live network sessions.
- ACP and external agent delegation:
  - Pending permissions and prompt tasks are process-local.

Recommendation: do not enable multiple app workers for live task execution
until either sticky routing is guaranteed per chat/session or task execution is
split into a dedicated worker queue with Redis/Postgres coordination.

## Durable Data Routed Through Repositories

These durable data surfaces now select SQLAlchemy repositories when
`QWENPAW_DATABASE_BACKEND=postgres`, while retaining SQLite compatibility
implementations for rollback:

- Chat/session hot path:
  - `src/qwenpaw/app/runner/repo/sqlalchemy_repo.py`
  - `src/qwenpaw/app/runner/session_sqlalchemy.py`
  - `src/qwenpaw/app/workspace/service_factories.py`
- Auth, admin users, and chat access:
  - `src/qwenpaw/app/storage/repos/user_repo.py`
  - `src/qwenpaw/app/auth.py`
  - `src/qwenpaw/app/chat_access.py`
  - `src/qwenpaw/app/routers/admin_users.py`
- Token usage and recent chat lists:
  - `src/qwenpaw/app/storage/repos/token_usage_repo.py`
  - `src/qwenpaw/app/storage/repos/chat_list_repo.py`
  - `src/qwenpaw/token_usage/manager.py`
  - `src/qwenpaw/app/routers/agents.py`
- MCP connections, capability injection, workspace preview context, and audit:
  - `src/qwenpaw/app/storage/repos/capability_repo.py`
  - `src/qwenpaw/app/storage/repos/workspace_context_repo.py`
  - `src/qwenpaw/app/storage/repos/audit_repo.py`
  - `src/qwenpaw/app/mcp/connections_db.py`
  - `src/qwenpaw/app/workspace/capabilities_injector.py`
  - `src/qwenpaw/app/routers/workspace.py`
  - `src/qwenpaw/app/routers/audit.py`
- Expert team templates, runs, and member runs:
  - `src/qwenpaw/app/storage/repos/expert_team_repo.py`
  - `src/qwenpaw/app/expert_teams.py`

The remaining `get_db()` matches are now expected in SQLite fallback
implementations, the base SQLite helper, and SQLite-specific diagnostics.

## Next Migration Order

1. Run a real Postgres/Redis smoke migration in Docker and verify diagnostics
   reports `storage.database_backend=postgres`, `postgres.connected=true`,
   and `postgres.tables.missing=[]`.
2. Decide live execution architecture: sticky-session routing for current
   single-container deployment, or a dedicated worker queue for true
   multi-worker execution.
3. Move channel gateway state and task stream reconnection state out of the app
   process before enabling non-sticky multi-worker mode.

## Current Decision

Postgres/Redis mode is suitable for staged development and smoke testing. It is
not yet approved for multiple app workers because live task/workspace/channel
state remains process-local. Durable business data is now mostly routed through
Postgres-capable repositories, so the next blocker is execution affinity or an
external worker queue rather than ordinary CRUD storage.
