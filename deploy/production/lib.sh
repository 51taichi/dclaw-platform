#!/usr/bin/env bash

DEPLOY_ROOT=${DCLAW_DEPLOY_ROOT:-/opt/dclaw-deploy}
IMAGE_REPOSITORY=${DCLAW_IMAGE_REPOSITORY:-ghcr.io/51taichi/dclaw}
COMPOSE_FILE="$DEPLOY_ROOT/compose.production.yml"
PRODUCTION_ENV="$DEPLOY_ROOT/production.env"
RELEASE_ENV="$DEPLOY_ROOT/release.env"
DEPLOY_LOCK="$DEPLOY_ROOT/deploy.lock"
LOCAL_HEALTH_URL=http://127.0.0.1:18088/api/version
PUBLIC_HEALTH_URL=https://dclaw.deepmega.cn/api/version
SERVER_LABEL=cn.deepmega.dclaw.server-revision
CLIENT_LABEL=cn.deepmega.dclaw.client-revision

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

validate_full_sha() {
  [[ $1 =~ ^[0-9a-f]{40}$ ]] || die "revision must be a full 40-character lowercase hexadecimal SHA"
}

validate_immutable_digest() {
  [[ $1 =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$|^sha256:[0-9a-f]{64}$ ]] ||
    die "image must be an immutable sha256 digest or local image ID"
}

acquire_deploy_lock() {
  mkdir -p "$DEPLOY_ROOT"
  exec 9>"$DEPLOY_LOCK"
  flock -n 9 || die "deployment already in progress"
}

image_id() {
  docker image inspect "$1" --format '{{.Id}}'
}

image_repo_digest() {
  docker image inspect "$1" --format '{{index .RepoDigests 0}}'
}

image_label() {
  local image=$1
  local label=$2
  docker image inspect "$image" --format "{{index .Config.Labels \"$label\"}}"
}

running_image_id() {
  docker inspect dclaw --format '{{.Image}}'
}

assert_runtime_resources() {
  docker inspect dclaw >/dev/null
  docker inspect dclaw-postgres >/dev/null
  docker inspect dclaw-redis >/dev/null
  docker network inspect dclaw-net >/dev/null
  docker volume inspect dclaw-data >/dev/null
  docker volume inspect dclaw-secrets >/dev/null
  docker volume inspect dclaw-backups >/dev/null
  test -f "$COMPOSE_FILE" || die "missing $COMPOSE_FILE"
  test -f "$PRODUCTION_ENV" || die "missing $PRODUCTION_ENV"
  test -f "$RELEASE_ENV" || die "missing $RELEASE_ENV"
}

validate_image_pair() {
  local image=$1
  local expected_server=${2:-}
  local expected_client=${3:-}
  RESOLVED_SERVER_SHA=$(image_label "$image" "$SERVER_LABEL")
  RESOLVED_CLIENT_SHA=$(image_label "$image" "$CLIENT_LABEL")
  validate_full_sha "$RESOLVED_SERVER_SHA"
  validate_full_sha "$RESOLVED_CLIENT_SHA"
  if [ -n "$expected_server" ]; then
    test "$RESOLVED_SERVER_SHA" = "$expected_server" || die "server revision label does not match requested SHA"
    test "$RESOLVED_CLIENT_SHA" = "$expected_client" || die "client revision label does not match requested SHA"
  fi
}

write_release_env() {
  local image=$1
  local server_sha=$2
  local client_sha=$3
  local temporary
  umask 077
  temporary=$(mktemp "$DEPLOY_ROOT/release.env.tmp.XXXXXX")
  {
    printf 'DCLAW_IMAGE=%s\n' "$image"
    printf 'SERVER_SHA=%s\n' "$server_sha"
    printf 'CLIENT_SHA=%s\n' "$client_sha"
  } >"$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$RELEASE_ENV"
}

backup_postgres() {
  local release_dir=$1
  local dump_tmp="$release_dir/pre-update.dump.tmp"
  local list_tmp="$release_dir/pre-update.list.tmp"
  umask 077
  if ! docker exec dclaw-postgres pg_dump -U qwenpaw -d qwenpaw --format=custom >"$dump_tmp"; then
    die "PostgreSQL backup creation failed"
  fi
  if ! docker run --rm --network none -v "$release_dir:/backup:ro" postgres:16-alpine \
    pg_restore --list /backup/pre-update.dump.tmp >"$list_tmp"; then
    die "PostgreSQL backup verification failed"
  fi
  test -s "$dump_tmp" || die "PostgreSQL backup is empty"
  test -s "$list_tmp" || die "PostgreSQL backup verification produced no entries"
  mv "$dump_tmp" "$release_dir/pre-update.dump"
  mv "$list_tmp" "$release_dir/pre-update.list"
  chmod 600 "$release_dir/pre-update.dump" "$release_dir/pre-update.list"
}

compose_recreate() {
  docker compose \
    --project-name dclaw-production \
    --project-directory "$DEPLOY_ROOT" \
    --env-file "$RELEASE_ENV" \
    -f "$COMPOSE_FILE" \
    up -d --no-deps --force-recreate dclaw
}

container_is_healthy_enough() {
  test "$(docker inspect dclaw --format '{{.State.Running}}')" = true || return 1
  test "$(docker inspect dclaw --format '{{.State.OOMKilled}}')" = false || return 1
  curl --fail --silent --show-error --connect-timeout 3 --max-time 10 \
    "$LOCAL_HEALTH_URL" >/dev/null
}

wait_for_health() {
  local timeout=$1
  local started=$SECONDS
  local interval=3
  if [ "${DCLAW_TESTING:-0}" = 1 ]; then
    interval=${DCLAW_TEST_HEALTH_INTERVAL:-3}
  fi
  while ((SECONDS - started < timeout)); do
    if container_is_healthy_enough; then
      return 0
    fi
    sleep "$interval"
  done
  return 1
}

verify_public_api() {
  curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
    "$PUBLIC_HEALTH_URL" >/dev/null
}

verify_running_identity() {
  local expected_id=$1
  local expected_server=$2
  local expected_client=$3
  local actual_id
  actual_id=$(running_image_id)
  test "$actual_id" = "$expected_id" || return 1
  test "$(image_label "$actual_id" "$SERVER_LABEL")" = "$expected_server" || return 1
  test "$(image_label "$actual_id" "$CLIENT_LABEL")" = "$expected_client"
}

save_failed_logs() {
  local release_dir=$1
  docker logs --tail 500 dclaw >"$release_dir/failed-container.log" 2>&1 || true
  chmod 600 "$release_dir/failed-container.log" 2>/dev/null || true
}

write_safe_facts() {
  local release_dir=$1
  local current_id=$2
  local current_digest=$3
  local current_server=$4
  local current_client=$5
  umask 077
  {
    printf 'image_id=%s\n' "$current_id"
    printf 'image_digest=%s\n' "$current_digest"
    printf 'server_sha=%s\n' "$current_server"
    printf 'client_sha=%s\n' "$current_client"
    docker inspect dclaw --format \
      'status={{.State.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}'
  } >"$release_dir/production-facts.txt"
  chmod 600 "$release_dir/production-facts.txt"
}

write_manifest() {
  local release_dir=$1
  local result=$2
  local previous_image=$3
  local target_image=$4
  local server_sha=$5
  local client_sha=$6
  umask 077
  python3 - "$release_dir/manifest.json" "$result" "$previous_image" "$target_image" "$server_sha" "$client_sha" <<'PY'
import json
import os
import sys
from pathlib import Path

path, result, previous, target, server, client = sys.argv[1:]
Path(path).write_text(json.dumps({
    "result": result,
    "previous_image": previous,
    "target_image": target,
    "server_sha": server,
    "client_sha": client,
}, indent=2) + "\n")
os.chmod(path, 0o600)
PY
}
