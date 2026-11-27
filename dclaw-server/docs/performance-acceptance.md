# QwenPaw SaaS Performance Acceptance

This stage keeps the current single-container deployment and adds repeatable
checks before deciding whether Redis/Postgres/workers are needed.

## What To Run

Set a token when authentication is enabled:

```bash
export QWENPAW_PERF_TOKEN='paste-your-login-token-here'
```

Run a production smoke check:

```bash
python scripts/perf/smoke_check.py \
  --base-url http://127.0.0.1:18088 \
  --json-output perf-smoke.json
```

Run the default idle-tab load test. The defaults simulate 300 idle browser
tabs polling every 15 seconds, which is about 20 requests per second.

```bash
python scripts/perf/load_test.py \
  --base-url http://127.0.0.1:18088 \
  --users 300 \
  --duration 120 \
  --poll-interval 15 \
  --p95-target-ms 300 \
  --max-error-rate 0.01 \
  --json-output perf-idle-300.json
```

For a smaller first run:

```bash
python scripts/perf/load_test.py \
  --base-url http://127.0.0.1:18088 \
  --users 100 \
  --duration 60 \
  --json-output perf-idle-100.json
```

## Auth Options

The scripts support the same Bearer token used by the console:

```bash
python scripts/perf/load_test.py --token "$QWENPAW_PERF_TOKEN"
```

They also support custom headers for proxies:

```bash
python scripts/perf/load_test.py \
  --header 'X-Forwarded-Proto: https' \
  --header 'X-Test-Run: perf-acceptance'
```

## Acceptance Targets

The first production target for one company with 100-300 people is:

- Idle 300-tab p95 below 300 ms.
- Error rate below 1%.
- SQLite mode: `/api/admin/performance/diagnostics` reports
  `sqlite.journal_mode=wal`.
- SQLite mode: `sqlite.busy_timeout` is at least 5000 ms.
- Postgres mode: diagnostics reports `postgres.connected=true`.
- Postgres mode: diagnostics reports `postgres.tables.missing=[]`.
- Redis runtime mode: diagnostics reports `task_limits.backend=redis`.
- Task limit has headroom and reports `running_global`,
  `rejected_acquire_count`, and `expired_permit_count`.
- Runtime diagnostics includes `task_stream_buffers` for loaded agents; dropped
  buffer events may increase during very long tasks, but buffer bytes should
  remain bounded.
- No sustained `database is locked` errors in application logs.

If the idle test passes but real task execution still feels slow, run a
separate task-execution test manually because it may spend model quota.

## How To Interpret Failures

- High p95 with low CPU: inspect slow requests in diagnostics and SQLite lock
  logs first.
- High p95 with high CPU: reduce frontend polling further or split static
  assets through Nginx cache.
- High error rate with 401/403: token or permission issue, not performance.
- High error rate with 429: task limiter is protecting the app; tune limits or
  queue UX before adding more workers.
- Sustained SQLite lock waits: this is the signal to plan Postgres or
  incremental message writes.

## Server Commands

From the deployed repository:

```bash
cd /opt/qwenpaw
export QWENPAW_PERF_TOKEN='paste-token'

python scripts/perf/smoke_check.py \
  --base-url http://127.0.0.1:18088 \
  --json-output /tmp/qwenpaw-perf-smoke.json

python scripts/perf/load_test.py \
  --base-url http://127.0.0.1:18088 \
  --users 300 \
  --duration 120 \
  --json-output /tmp/qwenpaw-perf-idle-300.json
```

If the server only has the Docker image but not Python dependencies outside the
container, run the scripts inside the repo checkout after pulling code, or use:

```bash
docker exec -it dclaw python /app/scripts/perf/smoke_check.py \
  --base-url http://127.0.0.1:8088
```

Only use the Docker command after the scripts are copied into the image.

## Postgres/Redis SaaS Mode

The default Compose service still runs the existing single-container
SQLite/in-memory mode:

```bash
docker compose up -d qwenpaw
```

For the SaaS profile, set a Postgres password and start the explicit SaaS app
service with Postgres and Redis:

```bash
export QWENPAW_POSTGRES_PASSWORD='replace-with-a-strong-password'
export QWENPAW_IMAGE='dclaw-local:latest'

docker compose --profile saas up -d postgres redis qwenpaw-saas
```

Run the same acceptance checks against the SaaS port:

```bash
python scripts/perf/smoke_check.py \
  --base-url http://127.0.0.1:18088

python scripts/perf/load_test.py \
  --base-url http://127.0.0.1:18088 \
  --users 100 \
  --duration 60 \
  --poll-interval 15 \
  --p95-target-ms 300 \
  --max-error-rate 0.01
```

Diagnostics should show:

- `storage.database_backend=postgres`
- `storage.runtime_backend=redis`
- `postgres.connected=true`
- `postgres.tables.missing=[]`
- `push_messages.backend=redis`
- `approvals.backend=redis`
- `task_limits.backend=redis`

Recommended first production limits for the current 4 vCPU / 16 GiB class:

```bash
QWENPAW_MAX_RUNNING_TASKS=32
QWENPAW_MAX_RUNNING_TASKS_PER_USER=6
QWENPAW_MAX_RUNNING_TASKS_PER_AGENT=12
QWENPAW_DATABASE_POOL_SIZE=10
QWENPAW_DATABASE_MAX_OVERFLOW=20
QWENPAW_TASK_STREAM_MAX_BUFFER_EVENTS=200
QWENPAW_TASK_STREAM_MAX_BUFFER_BYTES=524288
```

Detailed Aliyun Docker commands and rollback steps are in
`docs/deployment-postgres-redis.md`.
