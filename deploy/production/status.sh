#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=deploy/production/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command docker
require_command curl

echo '=== DClaw application ==='
docker inspect dclaw --format \
  'status={{.State.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}'
CURRENT_ID=$(running_image_id)
CURRENT_DIGEST=$(image_repo_digest "$CURRENT_ID" 2>/dev/null || true)
printf 'image_id=%s\n' "$CURRENT_ID"
printf 'repo_digest=%s\n' "${CURRENT_DIGEST:-unavailable}"
printf 'server_sha=%s\n' "$(image_label "$CURRENT_ID" "$SERVER_LABEL")"
printf 'client_sha=%s\n' "$(image_label "$CURRENT_ID" "$CLIENT_LABEL")"

echo '=== GHCR main (read-only) ==='
docker buildx imagetools inspect "${IMAGE_REPOSITORY}:main" \
  --format '{{json .Image.Config.Labels}}' 2>/dev/null || echo 'remote_labels=unavailable'

echo '=== dependencies ==='
for container in dclaw-postgres dclaw-redis; do
  printf '%s=' "$container"
  docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null || echo missing
done
printf 'dclaw-net='
docker network inspect dclaw-net --format '{{.Name}}' 2>/dev/null || echo missing
for volume in dclaw-data dclaw-secrets dclaw-backups; do
  printf '%s=' "$volume"
  docker volume inspect "$volume" --format '{{.Name}}' 2>/dev/null || echo missing
done

echo '=== API ==='
if curl --fail --silent --show-error --connect-timeout 3 --max-time 10 \
  "$LOCAL_HEALTH_URL" >/dev/null; then
  echo 'local_api=ok'
else
  echo 'local_api=failed'
fi
if curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
  "$PUBLIC_HEALTH_URL" >/dev/null; then
  echo 'public_api=ok'
else
  echo 'public_api=failed'
fi

echo '=== releases ==='
if [ -s "$DEPLOY_ROOT/LATEST_SUCCESS" ]; then
  latest=$(cat "$DEPLOY_ROOT/LATEST_SUCCESS")
  printf 'latest_success=%s\n' "$latest"
  if [ -f "$latest/manifest.json" ]; then
    python3 - "$latest/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for key in ("result", "previous_image", "target_image", "server_sha", "client_sha"):
    print(f"{key}={manifest.get(key, 'unavailable')}")
PY
  fi
else
  echo 'latest_success=unavailable'
fi
