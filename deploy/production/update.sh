#!/usr/bin/env bash
set -euo pipefail

HEALTH_TIMEOUT=420
if [ "${DCLAW_TESTING:-0}" = 1 ]; then
  HEALTH_TIMEOUT=${DCLAW_TEST_HEALTH_TIMEOUT:-420}
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=deploy/production/lib.sh
source "$SCRIPT_DIR/lib.sh"

SERVER_SHA=
CLIENT_SHA=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --server-sha)
      test "$#" -ge 2 || die "--server-sha requires a value"
      SERVER_SHA=$2
      shift 2
      ;;
    --client-sha)
      test "$#" -ge 2 || die "--client-sha requires a value"
      CLIENT_SHA=$2
      shift 2
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -n "$SERVER_SHA" ] || [ -n "$CLIENT_SHA" ]; then
  test -n "$SERVER_SHA" && test -n "$CLIENT_SHA" || die "both --server-sha and --client-sha are required"
  validate_full_sha "$SERVER_SHA"
  validate_full_sha "$CLIENT_SHA"
  TARGET_TAG="server-${SERVER_SHA:0:12}-client-${CLIENT_SHA:0:12}"
else
  TARGET_TAG=main
fi

require_command docker
require_command curl
require_command flock
require_command python3
acquire_deploy_lock
assert_runtime_resources

TARGET_REFERENCE="$IMAGE_REPOSITORY:$TARGET_TAG"
docker pull "$TARGET_REFERENCE" >/dev/null
TARGET_ID=$(image_id "$TARGET_REFERENCE")
TARGET_DIGEST=$(image_repo_digest "$TARGET_REFERENCE")
validate_immutable_digest "$TARGET_DIGEST"
validate_image_pair "$TARGET_REFERENCE" "$SERVER_SHA" "$CLIENT_SHA"

CURRENT_ID=$(running_image_id)
if [ "$TARGET_ID" = "$CURRENT_ID" ]; then
  print_release_result NO_UPDATE_REQUIRED
  exit 0
fi

CURRENT_DIGEST=$(image_repo_digest "$CURRENT_ID" 2>/dev/null || true)
CURRENT_SERVER_SHA=$(image_label "$CURRENT_ID" "$SERVER_LABEL")
CURRENT_CLIENT_SHA=$(image_label "$CURRENT_ID" "$CLIENT_LABEL")
validate_full_sha "$CURRENT_SERVER_SHA"
validate_full_sha "$CURRENT_CLIENT_SHA"

timestamp=$(date +%Y%m%d-%H%M%S)
release_dir="$DEPLOY_ROOT/releases/$timestamp"
mkdir -p "$release_dir"
chmod 700 "$release_dir"
write_safe_facts "$release_dir" "$CURRENT_ID" "$CURRENT_DIGEST" "$CURRENT_SERVER_SHA" "$CURRENT_CLIENT_SHA"
docker tag "$CURRENT_ID" "dclaw-local:rollback-$timestamp"
backup_postgres "$release_dir"

write_release_env "$TARGET_DIGEST" "$RESOLVED_SERVER_SHA" "$RESOLVED_CLIENT_SHA"

update_ok=false
if compose_recreate && wait_for_health "$HEALTH_TIMEOUT" && verify_public_api && \
  verify_running_identity "$TARGET_ID" "$RESOLVED_SERVER_SHA" "$RESOLVED_CLIENT_SHA"; then
  update_ok=true
fi

if [ "$update_ok" = true ]; then
  write_manifest "$release_dir" UPDATE_SUCCESS "$CURRENT_ID" "$TARGET_DIGEST" \
    "$RESOLVED_SERVER_SHA" "$RESOLVED_CLIENT_SHA"
  printf '%s\n' "$release_dir" >"$DEPLOY_ROOT/LATEST_SUCCESS"
  chmod 600 "$DEPLOY_ROOT/LATEST_SUCCESS"
  print_release_result UPDATE_SUCCESS
  exit 0
fi

save_failed_logs "$release_dir"
write_release_env "$CURRENT_ID" "$CURRENT_SERVER_SHA" "$CURRENT_CLIENT_SHA"
if compose_recreate && wait_for_health "$HEALTH_TIMEOUT" && verify_public_api && \
  verify_running_identity "$CURRENT_ID" "$CURRENT_SERVER_SHA" "$CURRENT_CLIENT_SHA"; then
  write_manifest "$release_dir" UPDATE_FAILED_ROLLBACK_READY "$CURRENT_ID" "$TARGET_DIGEST" \
    "$RESOLVED_SERVER_SHA" "$RESOLVED_CLIENT_SHA"
  echo UPDATE_FAILED_ROLLBACK_READY
  exit 1
fi

echo ROLLBACK_FAILED >&2
exit 2
