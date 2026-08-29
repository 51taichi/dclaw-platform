#!/usr/bin/env bash
set -euo pipefail

HEALTH_TIMEOUT=420
if [ "${DCLAW_TESTING:-0}" = 1 ]; then
  HEALTH_TIMEOUT=${DCLAW_TEST_HEALTH_TIMEOUT:-420}
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=deploy/production/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command docker
require_command curl
require_command flock
acquire_deploy_lock

test -f "$COMPOSE_FILE" || die "missing $COMPOSE_FILE"
docker inspect dclaw >/dev/null || die "current dclaw container is missing"
docker inspect dclaw-postgres >/dev/null || die "dclaw-postgres is missing"
docker inspect dclaw-redis >/dev/null || die "dclaw-redis is missing"
docker network inspect dclaw-net >/dev/null || die "dclaw-net is missing"
docker volume inspect dclaw-data >/dev/null || die "dclaw-data is missing"
docker volume inspect dclaw-secrets >/dev/null || die "dclaw-secrets is missing"
docker volume inspect dclaw-backups >/dev/null || die "dclaw-backups is missing"

test "$(docker inspect dclaw --format '{{.HostConfig.RestartPolicy.Name}}')" = unless-stopped ||
  die "current restart policy is not unless-stopped"
test "$(docker inspect dclaw --format '{{range $port, $bindings := .NetworkSettings.Ports}}{{range $bindings}}{{.HostIp}}:{{.HostPort}}:{{$port}}{{end}}{{end}}')" = \
  127.0.0.1:18088:8088/tcp || die "current port binding is not 127.0.0.1:18088:8088"

networks=$(docker inspect dclaw --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}')
test "$networks" = dclaw-net || die "current application network is not exactly dclaw-net"
mounts=$(docker inspect dclaw --format '{{range .Mounts}}{{printf "%s|%s\n" .Name .Destination}}{{end}}')
for required in \
  'dclaw-data|/app/working' \
  'dclaw-secrets|/app/working.secret' \
  'dclaw-backups|/app/working.backups'; do
  printf '%s\n' "$mounts" | grep -Fqx "$required" || die "required mount is missing: $required"
done
test "$(printf '%s\n' "$mounts" | sed '/^$/d' | wc -l | tr -d ' ')" = 3 ||
  die "current application has unexpected additional mounts"

CURRENT_ID=$(running_image_id)
CURRENT_DIGEST=$(image_repo_digest "$CURRENT_ID" 2>/dev/null || true)
CURRENT_IMAGE=${CURRENT_DIGEST:-$CURRENT_ID}
validate_immutable_digest "$CURRENT_IMAGE"
CURRENT_SERVER_SHA=$(image_label "$CURRENT_ID" "$SERVER_LABEL")
CURRENT_CLIENT_SHA=$(image_label "$CURRENT_ID" "$CLIENT_LABEL")
validate_full_sha "$CURRENT_SERVER_SHA"
validate_full_sha "$CURRENT_CLIENT_SHA"

timestamp=$(date +%Y%m%d-%H%M%S)
adoption_dir="$DEPLOY_ROOT/adoptions/$timestamp"
rollback_name="dclaw-before-$timestamp"
mkdir -p "$adoption_dir"
chmod 700 "$adoption_dir"
write_safe_facts "$adoption_dir" "$CURRENT_ID" "$CURRENT_DIGEST" "$CURRENT_SERVER_SHA" "$CURRENT_CLIENT_SHA"
backup_postgres "$adoption_dir"

umask 077
environment_tmp=$(mktemp "$DEPLOY_ROOT/production.env.tmp.XXXXXX")
docker inspect dclaw --format '{{range .Config.Env}}{{println .}}{{end}}' >"$environment_tmp"
if grep -q $'\r' "$environment_tmp" || grep -Evq '^[A-Za-z_][A-Za-z0-9_]*=.*$' "$environment_tmp"; then
  rm -f "$environment_tmp"
  die "current container environment contains an unsupported entry"
fi
chmod 600 "$environment_tmp"
mv "$environment_tmp" "$PRODUCTION_ENV"
write_release_env "$CURRENT_IMAGE" "$CURRENT_SERVER_SHA" "$CURRENT_CLIENT_SHA"
docker tag "$CURRENT_ID" "dclaw-local:pre-compose-$timestamp"

docker stop dclaw >/dev/null
docker rename dclaw "$rollback_name"

if compose_recreate && wait_for_health "$HEALTH_TIMEOUT" && verify_public_api && \
  verify_running_identity "$CURRENT_ID" "$CURRENT_SERVER_SHA" "$CURRENT_CLIENT_SHA"; then
  printf '%s\n' "$adoption_dir" >"$DEPLOY_ROOT/LATEST_ADOPTION"
  chmod 600 "$DEPLOY_ROOT/LATEST_ADOPTION"
  echo ADOPTION_SUCCESS
  exit 0
fi

save_failed_logs "$adoption_dir"
docker rm -f dclaw >/dev/null 2>&1 || true
docker rename "$rollback_name" dclaw
docker start dclaw >/dev/null
if wait_for_health "$HEALTH_TIMEOUT"; then
  die "adoption failed; original production restored"
fi
die "adoption failed and original production could not be restored"
