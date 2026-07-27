# QwenPaw Postgres/Redis Deployment

This guide keeps the existing SQLite/in-memory deployment reversible while
adding a Postgres + Redis rollout path for a single-company SaaS deployment.

## Environment

Use placeholders; do not paste real passwords into this file.

```bash
export APP_DIR=/opt/qwenpaw
export APP_IMAGE=dclaw-local:latest
export APP_CONTAINER=dclaw
export APP_PORT=18088
export QWENPAW_POSTGRES_PASSWORD='replace-with-a-strong-password'
export QWENPAW_DATABASE_URL="postgresql+psycopg://qwenpaw:${QWENPAW_POSTGRES_PASSWORD}@dclaw-postgres:5432/qwenpaw"
export QWENPAW_REDIS_URL='redis://dclaw-redis:6379/0'
```

## 1. Back Up Current Volumes

```bash
mkdir -p /opt/qwenpaw-backups

docker run --rm \
  -v dclaw-data:/volume:ro \
  -v /opt/qwenpaw-backups:/backup \
  alpine sh -c 'cd /volume && tar czf /backup/dclaw-data-$(date +%Y%m%d%H%M%S).tgz .'

docker run --rm \
  -v dclaw-secrets:/volume:ro \
  -v /opt/qwenpaw-backups:/backup \
  alpine sh -c 'cd /volume && tar czf /backup/dclaw-secrets-$(date +%Y%m%d%H%M%S).tgz .'

docker run --rm \
  -v dclaw-backups:/volume:ro \
  -v /opt/qwenpaw-backups:/backup \
  alpine sh -c 'cd /volume && tar czf /backup/dclaw-backups-$(date +%Y%m%d%H%M%S).tgz .'
```

## 2. Pull And Build

If the server keeps local Dockerfile mirror edits, stash them before pulling and
pop them after pulling.

```bash
cd "$APP_DIR"

git status --short
git stash push -m "server dockerfile mirror overrides" -- deploy/Dockerfile || true
git pull --ff-only origin codex/aigc-studio
git stash pop || true

docker build -f deploy/Dockerfile -t "$APP_IMAGE" .
```

## 3. Start Postgres And Redis

```bash
docker network create dclaw-net || true
docker volume create dclaw-postgres
docker volume create dclaw-redis

docker rm -f dclaw-postgres dclaw-redis 2>/dev/null || true

docker run -d \
  --name dclaw-postgres \
  --restart unless-stopped \
  --network dclaw-net \
  -e POSTGRES_DB=qwenpaw \
  -e POSTGRES_USER=qwenpaw \
  -e POSTGRES_PASSWORD="$QWENPAW_POSTGRES_PASSWORD" \
  -v dclaw-postgres:/var/lib/postgresql/data \
  postgres:16-alpine

docker run -d \
  --name dclaw-redis \
  --restart unless-stopped \
  --network dclaw-net \
  -v dclaw-redis:/data \
  redis:7-alpine \
  redis-server --appendonly yes

until docker exec dclaw-postgres pg_isready -U qwenpaw -d qwenpaw; do sleep 2; done
until docker exec dclaw-redis redis-cli ping | grep -q PONG; do sleep 2; done
```

## 4. Migrate SQLite To Postgres

Dry-run first:

```bash
docker run --rm \
  --network dclaw-net \
  -e QWENPAW_DATABASE_URL="$QWENPAW_DATABASE_URL" \
  -v dclaw-secrets:/app/working.secret \
  "$APP_IMAGE" \
  python /app/scripts/db/migrate_sqlite_to_postgres.py \
    --sqlite-path /app/working.secret/qwenpaw.db \
    --postgres-url "$QWENPAW_DATABASE_URL" \
    --dry-run
```

Execute once the dry-run output looks right:

```bash
docker run --rm \
  --network dclaw-net \
  -e QWENPAW_DATABASE_URL="$QWENPAW_DATABASE_URL" \
  -v dclaw-secrets:/app/working.secret \
  "$APP_IMAGE" \
  python /app/scripts/db/migrate_sqlite_to_postgres.py \
    --sqlite-path /app/working.secret/qwenpaw.db \
    --postgres-url "$QWENPAW_DATABASE_URL" \
    --execute
```

If you intentionally need to re-run against a non-empty target, add
`--allow-non-empty-target` only after checking the target row counts.

## 5. Restart App In Postgres/Redis Mode

```bash
docker rm -f "$APP_CONTAINER" 2>/dev/null || true

docker run -d \
  --name "$APP_CONTAINER" \
  --restart unless-stopped \
  --network dclaw-net \
  -p 127.0.0.1:${APP_PORT}:8088 \
  -e QWENPAW_AUTH_ENABLED=true \
  -e QWENPAW_DATABASE_BACKEND=postgres \
  -e QWENPAW_DATABASE_URL="$QWENPAW_DATABASE_URL" \
  -e QWENPAW_RUNTIME_BACKEND=redis \
  -e QWENPAW_REDIS_URL="$QWENPAW_REDIS_URL" \
  -v dclaw-data:/app/working \
  -v dclaw-secrets:/app/working.secret \
  -v dclaw-backups:/app/working.backups \
  "$APP_IMAGE"

docker logs --tail=120 "$APP_CONTAINER"
```

## 6. Smoke And Short Load Check

If auth is enabled and the checks return 401/403, export a valid console bearer
token first:

```bash
export QWENPAW_PERF_TOKEN='paste-token-if-needed'
```

```bash
docker exec "$APP_CONTAINER" \
  python /app/scripts/perf/smoke_check.py \
    --base-url http://127.0.0.1:8088

docker exec "$APP_CONTAINER" \
  python /app/scripts/perf/load_test.py \
    --base-url http://127.0.0.1:8088 \
    --users 100 \
    --duration 60 \
    --poll-interval 15 \
    --p95-target-ms 300 \
    --max-error-rate 0.01
```

Check diagnostics:

```bash
curl -s http://127.0.0.1:${APP_PORT}/api/admin/performance/diagnostics | python -m json.tool
```

Expected storage/runtime signals:

- `storage.database_backend` is `postgres`.
- `storage.runtime_backend` is `redis`.
- `postgres.connected` is `true`.
- `postgres.tables.missing` is an empty list.
- `push_messages.backend` is `redis`.
- `approvals.backend` is `redis`.
- `task_limits.backend` is `redis`.

## Rollback To SQLite/In-Memory

Rollback does not delete any volumes.

```bash
docker rm -f "$APP_CONTAINER" 2>/dev/null || true

docker run -d \
  --name "$APP_CONTAINER" \
  --restart unless-stopped \
  -p 127.0.0.1:${APP_PORT}:8088 \
  -e QWENPAW_AUTH_ENABLED=true \
  -v dclaw-data:/app/working \
  -v dclaw-secrets:/app/working.secret \
  -v dclaw-backups:/app/working.backups \
  "$APP_IMAGE"

docker logs --tail=120 "$APP_CONTAINER"
```

After rollback is confirmed, you may stop Postgres and Redis without deleting
their volumes:

```bash
docker stop dclaw-postgres dclaw-redis
```

Do not remove `dclaw-postgres`, `dclaw-redis`, `dclaw-data`,
`dclaw-secrets`, or `dclaw-backups` until a separate backup has been verified.
