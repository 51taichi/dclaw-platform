# OpenAPI credit billing production rollout

This repository ships one production Compose file, `docker-compose.yml`.
Its SaaS application service is `qwenpaw-saas` on host port
`QWENPAW_SAAS_HOST_PORT` (default `18088`), with `postgres:16-alpine` and
`redis:7-alpine`. PostgreSQL, Redis AOF, working data, secrets, and application
backups use the explicitly named volumes `qwenpaw-postgres`, `qwenpaw-redis`,
`qwenpaw-data`, `qwenpaw-secrets`, and `qwenpaw-backups`.

The repository does not contain an Nginx site file. The commands below assume
the approved external site already includes
`/etc/nginx/qwenpaw/upstream-active.conf` and proxies to
`http://qwenpaw_backend`. If `nginx -T` does not prove both facts, stop and
have the site owner prepare that separately.

Never attach a candidate to production volumes or the production database.
Run commands with shell tracing disabled and never copy secrets into a ticket.

## 1. Validate explicit operator variables

Run from a root-capable deployment shell. Set the release-specific values;
the checks deliberately reject empty, relative, root, and reused ports.

```bash
set -eu
set +x
REPO_DIR=/srv/qwenpaw
CHANGE_ID=billing-20260829-01
CHANGE_DIR=/var/backups/qwenpaw/${CHANGE_ID}
CANDIDATE_PROJECT=qwenpaw-billing-candidate
CANDIDATE_PORT=28088
RELEASE_PORT=28089
CANDIDATE_IMAGE=registry.example/qwenpaw@sha256:REPLACE_WITH_DIGEST
PRODUCTION_PORT=18088
ADMIN_TOKEN_FILE=/run/secrets/qwenpaw-admin-token
NGINX_DIR=/etc/nginx/qwenpaw
NGINX_ACTIVE=${NGINX_DIR}/upstream-active.conf

case "$REPO_DIR" in /*) ;; *) exit 2 ;; esac
case "$CHANGE_DIR" in /var/backups/qwenpaw/*) ;; *) exit 2 ;; esac
test "$CHANGE_DIR" != /var/backups/qwenpaw
test "$CANDIDATE_PORT" -ne "$PRODUCTION_PORT"
test "$RELEASE_PORT" -ne "$PRODUCTION_PORT"
test "$RELEASE_PORT" -ne "$CANDIDATE_PORT"
test -d "$REPO_DIR"
test -f "$REPO_DIR/docker-compose.yml"
test -r "$ADMIN_TOKEN_FILE"
test "$(stat -c '%a' "$ADMIN_TOKEN_FILE")" = 600
case "$CANDIDATE_IMAGE" in *@sha256:*) ;; *) exit 2 ;; esac
install -d -m 0700 "$CHANGE_DIR"
cd "$REPO_DIR"
```

Keep these values in the same protected shell. Do not use broad deletion
commands or an unvalidated path to clean up.

## 2. Capture code, image, Compose, Nginx, database, and volumes

Record the exact running image ID/digest and source state, then save the image
and repository. No mutable tag is sufficient rollback evidence.

```bash
date -u +%FT%TZ > "$CHANGE_DIR/started-at.txt"
git rev-parse HEAD > "$CHANGE_DIR/source-commit.txt"
git status --short > "$CHANGE_DIR/source-status.txt"
git bundle create "$CHANGE_DIR/source.bundle" --all
cp docker-compose.yml "$CHANGE_DIR/docker-compose.yml"
docker compose --profile saas config > "$CHANGE_DIR/compose.rendered.yml"
docker compose --profile saas ps --all > "$CHANGE_DIR/compose.ps.txt"
docker inspect qwenpaw-saas > "$CHANGE_DIR/qwenpaw-saas.inspect.json"
PRODUCTION_IMAGE_ID="$(docker inspect --format '{{.Image}}' qwenpaw-saas)"
case "$PRODUCTION_IMAGE_ID" in sha256:*) ;; *) exit 2 ;; esac
docker image inspect "$PRODUCTION_IMAGE_ID" \
  > "$CHANGE_DIR/production-image.inspect.json"
docker image save -o "$CHANGE_DIR/production-image.tar" \
  "$PRODUCTION_IMAGE_ID"

sudo nginx -T > "$CHANGE_DIR/nginx.full.conf" 2>&1
sudo nginx -t
test -L "$NGINX_ACTIVE"
readlink -f "$NGINX_ACTIVE" > "$CHANGE_DIR/nginx-active-target.txt"
sha256sum "$CHANGE_DIR/nginx.full.conf" "$(readlink -f "$NGINX_ACTIVE")" \
  > "$CHANGE_DIR/nginx.sha256"
grep -F '/etc/nginx/qwenpaw/upstream-active.conf' \
  "$CHANGE_DIR/nginx.full.conf"
grep -F 'proxy_pass http://qwenpaw_backend' \
  "$CHANGE_DIR/nginx.full.conf"
```

Create and validate logical PostgreSQL backups while production is healthy.

```bash
docker compose --profile saas exec -T postgres \
  pg_dump -U qwenpaw -d qwenpaw -Fc \
  > "$CHANGE_DIR/qwenpaw.pre-billing.dump"
docker compose --profile saas exec -T postgres \
  pg_dump -U qwenpaw -d qwenpaw --schema-only \
  > "$CHANGE_DIR/qwenpaw.pre-billing.schema.sql"
docker run --rm -i postgres:16-alpine pg_restore --list \
  < "$CHANGE_DIR/qwenpaw.pre-billing.dump" \
  > "$CHANGE_DIR/qwenpaw.pre-billing.dump.list"
test -s "$CHANGE_DIR/qwenpaw.pre-billing.dump"
test -s "$CHANGE_DIR/qwenpaw.pre-billing.dump.list"
```

The application volumes need a short write pause for a coherent archive.
The secrets archive is restricted material.

```bash
docker compose --profile saas stop qwenpaw-saas
for VOLUME_NAME in qwenpaw-data qwenpaw-secrets qwenpaw-backups; do
  docker volume inspect "$VOLUME_NAME" \
    > "$CHANGE_DIR/${VOLUME_NAME}.inspect.json"
  docker run --rm -v "${VOLUME_NAME}:/source:ro" \
    -v "$CHANGE_DIR:/backup" alpine:3.20 \
    tar -C /source -czf "/backup/${VOLUME_NAME}.tgz" .
done
docker compose --profile saas start qwenpaw-saas
```

Compose configures Redis with
`command: ["redis-server", "--appendonly", "yes"]`; therefore
`qwenpaw-redis` is persistent, not an anonymous disposable cache. Drain or
pause new jobs, then archive it consistently. If incident command elects not
to restore it, document that in-flight runtime state can be lost and rely only
on the separately tested durable PostgreSQL recovery path.

```bash
docker compose --profile saas stop qwenpaw-saas redis
docker volume inspect qwenpaw-redis \
  > "$CHANGE_DIR/qwenpaw-redis.inspect.json"
docker run --rm -v qwenpaw-redis:/source:ro -v "$CHANGE_DIR:/backup" \
  alpine:3.20 tar -C /source -czf /backup/qwenpaw-redis.tgz .
docker compose --profile saas start redis qwenpaw-saas
sha256sum "$CHANGE_DIR"/*.dump "$CHANGE_DIR"/*.tgz \
  > "$CHANGE_DIR/backups.sha256"
sha256sum -c "$CHANGE_DIR/backups.sha256"
```

A raw PostgreSQL volume copy is valid only with PostgreSQL stopped or from a
database-consistent storage snapshot. `pg_dump` above is the normal restore
authority; never live-tar `qwenpaw-postgres`.

## 3. Build a fully isolated candidate project

The override replaces every application/database/runtime volume, container
name, and host port. It never names `qwenpaw-postgres` or `qwenpaw-redis` as a
service mount.

```bash
cat > "$CHANGE_DIR/candidate.compose.yml" <<'YAML'
services:
  qwenpaw-saas:
    image: ${CANDIDATE_IMAGE:?candidate digest required}
    container_name: qwenpaw-billing-candidate-app
    ports:
      - "127.0.0.1:${CANDIDATE_PORT:?candidate port required}:8088"
    volumes:
      - candidate-data:/app/working
      - candidate-secrets:/app/working.secret
      - candidate-backups:/app/working.backups
  postgres:
    container_name: qwenpaw-billing-candidate-postgres
    volumes:
      - candidate-postgres:/var/lib/postgresql/data
  redis:
    container_name: qwenpaw-billing-candidate-redis
    volumes:
      - candidate-redis:/data
volumes:
  candidate-data:
    name: qwenpaw-billing-candidate-data
  candidate-secrets:
    name: qwenpaw-billing-candidate-secrets
  candidate-backups:
    name: qwenpaw-billing-candidate-backups
  candidate-postgres:
    name: qwenpaw-billing-candidate-postgres
  candidate-redis:
    name: qwenpaw-billing-candidate-redis
YAML

export CANDIDATE_IMAGE CANDIDATE_PORT
docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml \
  -f "$CHANGE_DIR/candidate.compose.yml" --profile saas config \
  > "$CHANGE_DIR/candidate.compose.rendered.yml"
grep -F 'qwenpaw-billing-candidate-postgres' \
  "$CHANGE_DIR/candidate.compose.rendered.yml"
grep -F 'qwenpaw-billing-candidate-redis' \
  "$CHANGE_DIR/candidate.compose.rendered.yml"
if grep -F 'source: qwenpaw-postgres' \
  "$CHANGE_DIR/candidate.compose.rendered.yml"; then exit 3; fi
if grep -F 'source: qwenpaw-redis' \
  "$CHANGE_DIR/candidate.compose.rendered.yml"; then exit 3; fi

docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml \
  -f "$CHANGE_DIR/candidate.compose.yml" --profile saas \
  up -d postgres redis
```

Restore only copies into the candidate. Restore application configuration and
secrets from the protected snapshots, then restore PostgreSQL before starting
the candidate app.

```bash
for VOLUME_NAME in data secrets backups; do
  docker run --rm \
    -v "qwenpaw-billing-candidate-${VOLUME_NAME}:/restore" \
    -v "$CHANGE_DIR:/backup:ro" alpine:3.20 \
    tar -C /restore -xzf "/backup/qwenpaw-${VOLUME_NAME}.tgz"
done
docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml \
  -f "$CHANGE_DIR/candidate.compose.yml" --profile saas exec -T postgres \
  pg_restore --exit-on-error --clean --if-exists \
  -U qwenpaw -d qwenpaw \
  < "$CHANGE_DIR/qwenpaw.pre-billing.dump"
docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml \
  -f "$CHANGE_DIR/candidate.compose.yml" --profile saas \
  up -d qwenpaw-saas
curl --fail --silent --show-error \
  "http://127.0.0.1:${CANDIDATE_PORT}/api/health"
```

Certify a fresh empty candidate database separately, then repeat against this
restored snapshot. Boot each twice. Confirm the reconciliation/rollout tables,
immutable audit triggers, and `idx_open_api_invocations_billing_usage_order`
exist and that migration changed no historical `unbilled`, ledger, or token
row. Run the SQLite and live-PostgreSQL billing/recovery/concurrency suites.

## 4. Catalog, wallet, shadow, and observe gates

Require a published effective retail catalog for every allowed
provider/model/capability/tier. Seed wallets only through an immutable grant
ledger primitive with a deterministic campaign/user idempotency key. Re-run
the seed and prove balances and ledger row counts do not change.

Use the protected admin token without printing it or placing it on a command
line as a literal:

```bash
set +x
ADMIN_TOKEN="$(<"$ADMIN_TOKEN_FILE")"
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"shadow"}' \
  "http://127.0.0.1:${CANDIDATE_PORT}/api/admin/billing/rollout/activate"
unset ADMIN_TOKEN
```

Shadow must cover normal agent, expert team/multi-call, timeout, disconnect,
retry, restart, catalog miss, and ambiguous evidence. Require zero wallet or
ledger mutation, zero duplicate events, no secret/cost/evidence/prompt leak,
and durable item totals within documented adapter tolerances. Analytics is
comparison data only and never repairs finance.

Activate `observe` the same way and measure would-block rates by user,
publication, application, model, and catalog. Observe must not hold/debit or
write `billing_cutover_at`. Do not promote with an unexplained interruption
cohort, missing wallet seed, unsupported output cap, or stale reconciliation.

## 5. Candidate canaries

Against `127.0.0.1:${CANDIDATE_PORT}`, verify authenticated wallet, ledger,
bounded summary, order list/detail, admin queue/audit filters, foreign-order
404, invalid cursor/date/limit rejection, idempotent replay, and no raw
supplier/evidence/cost/prompt/credential fields. Run funded, unfunded,
multi-call insufficiency, ambiguous evidence, SSE disconnect, and restart
canaries. Candidate writes must appear only in its restored PostgreSQL copy.

## 6. End isolated testing and start the approved production release

The isolated candidate is never promoted in place. Stop it after certification
while retaining its volumes for evidence. Only after change approval, start a
separate release container from the immutable candidate image. This release
intentionally uses the production Compose service configuration, network,
database, and named application volumes; from this point it is a production
writer, not a candidate.

```bash
docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml \
  -f "$CHANGE_DIR/candidate.compose.yml" --profile saas \
  down --remove-orphans
if docker ps --format '{{.Ports}}' | grep -F "127.0.0.1:${RELEASE_PORT}->"; then
  exit 3
fi
export QWENPAW_IMAGE="$CANDIDATE_IMAGE"
docker compose --profile saas run -d --name qwenpaw-release --no-deps \
  -p "127.0.0.1:${RELEASE_PORT}:8088" qwenpaw-saas
curl --fail --silent --show-error \
  "http://127.0.0.1:${RELEASE_PORT}/api/health"
```

Startup may now run additive migrations and fenced recovery against production.
Do not send customer traffic until health, migration logs, financial row-count
checks, and a read-only authenticated canary pass. Keep `qwenpaw-saas` serving
the old image on port `18088` until the Nginx switch.

## 7. Prepare and atomically switch Nginx

Create two immutable upstream fragments and keep the old one for rollback.
The active symlink is the only switch.

```bash
sudo install -d -m 0755 "$NGINX_DIR"
sudo tee "$NGINX_DIR/upstream-old.conf" >/dev/null <<EOF
upstream qwenpaw_backend {
    server 127.0.0.1:${PRODUCTION_PORT};
    keepalive 32;
}
EOF
sudo tee "$NGINX_DIR/upstream-release.conf" >/dev/null <<EOF
upstream qwenpaw_backend {
    server 127.0.0.1:${RELEASE_PORT};
    keepalive 32;
}
EOF
sudo sha256sum "$NGINX_DIR/upstream-old.conf" \
  "$NGINX_DIR/upstream-release.conf" \
  > "$CHANGE_DIR/nginx-upstreams.sha256"
sudo ln -sfn "$NGINX_DIR/upstream-release.conf" \
  "$NGINX_DIR/upstream-active.conf.next"
sudo mv -Tf "$NGINX_DIR/upstream-active.conf.next" "$NGINX_ACTIVE"
sudo nginx -t
sudo nginx -s reload
curl --fail --silent --show-error https://service.example/api/health
docker stop qwenpaw-saas
```

If `nginx -t` or the public health check fails, immediately execute the exact
revert below; do not edit the active config in place.

```bash
sudo ln -sfn "$NGINX_DIR/upstream-old.conf" \
  "$NGINX_DIR/upstream-active.conf.next"
sudo mv -Tf "$NGINX_DIR/upstream-active.conf.next" "$NGINX_ACTIVE"
sudo nginx -t
sudo nginx -s reload
```

## 8. Explicit enforced cutover and health checks

After production traffic is healthy on the candidate image and all gates are
approved, activate production exactly once. Only this authenticated endpoint
may write the first `billing_cutover_at`; repeat activation must retain the
original timestamp and actor.

```bash
set +x
ADMIN_TOKEN="$(<"$ADMIN_TOKEN_FILE")"
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"enforced"}' \
  "http://127.0.0.1:${RELEASE_PORT}/api/admin/billing/rollout/activate" \
  > "$CHANGE_DIR/enforced-activation.json"
unset ADMIN_TOKEN
```

Immediately repeat funded, replay, unfunded, incremental-insufficiency,
ambiguous, disconnect, and restart canaries. Monitor HTTP latency/errors,
supplier calls, wallet/lot/ledger projections, reconciliation age/rate,
PostgreSQL locks/deadlocks, Redis health, recovery logs, and Nginx upstream
health for the full observation window.

## 9. Rollback and database restore implications

For a billing-policy incident, first activate `observe`, `shadow`, or `off`
through the same authenticated API. This stops new wallet mutation but never
clears the cutover or reverses legitimate ledger entries.

For an application regression, stop `qwenpaw-release`, start the saved
`qwenpaw-saas` old-image container on port `18088`, then run the Nginx revert
in section 7. Keep the upgraded production
PostgreSQL database and named volumes. Task 6 schema/index changes are additive;
forward-compatible database reuse preserves all post-backup ledger, user,
message, invocation, and configuration writes and is the preferred rollback.

```bash
docker stop qwenpaw-release
docker start qwenpaw-saas
curl --fail --silent --show-error \
  "http://127.0.0.1:${PRODUCTION_PORT}/api/health"
sudo ln -sfn "$NGINX_DIR/upstream-old.conf" \
  "$NGINX_DIR/upstream-active.conf.next"
sudo mv -Tf "$NGINX_DIR/upstream-active.conf.next" "$NGINX_ACTIVE"
sudo nginx -t
sudo nginx -s reload
```

Restore PostgreSQL only if the migration corrupted data, the old binary is
demonstrably incompatible with the additive schema, or incident command
explicitly accepts point-in-time data loss. Stop all writers, take a final
forensic dump, restore the saved dump into a new database, validate financial
sums and canaries, then switch the connection. Never overwrite the only
database copy. Restoring the old dump discards every later billing and
non-billing write and requires reconciliation. A raw `qwenpaw-postgres` volume
restore is last resort and requires a consistency-certified snapshot and the
same PostgreSQL major version.

Do not delete new tables/indexes, reset `billing_cutover_at`, directly edit a
wallet/lot/ledger/audit, or synthesize refunds without a separately approved
financial correction workflow.
