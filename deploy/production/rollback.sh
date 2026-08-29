#!/usr/bin/env bash
set -euo pipefail

HEALTH_TIMEOUT=420
if [ "${DCLAW_TESTING:-0}" = 1 ]; then
  HEALTH_TIMEOUT=${DCLAW_TEST_HEALTH_TIMEOUT:-420}
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=deploy/production/lib.sh
source "$SCRIPT_DIR/lib.sh"

EXPLICIT_IMAGE=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --image)
      test "$#" -ge 2 || die "--image requires a value"
      EXPLICIT_IMAGE=$2
      shift 2
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

require_command docker
require_command curl
require_command flock
acquire_deploy_lock
assert_runtime_resources

if [ -n "$EXPLICIT_IMAGE" ]; then
  TARGET_IMAGE=$EXPLICIT_IMAGE
else
  test -s "$DEPLOY_ROOT/LATEST_SUCCESS" || die "no successful release manifest is available"
  latest=$(cat "$DEPLOY_ROOT/LATEST_SUCCESS")
  test -f "$latest/manifest.json" || die "latest release manifest is missing"
  TARGET_IMAGE=$(python3 - "$latest/manifest.json" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1], encoding="utf-8"))["previous_image"])
PY
  )
fi

validate_immutable_digest "$TARGET_IMAGE"
docker image inspect "$TARGET_IMAGE" >/dev/null
TARGET_ID=$(image_id "$TARGET_IMAGE")
TARGET_SERVER_SHA=$(image_label "$TARGET_IMAGE" "$SERVER_LABEL")
TARGET_CLIENT_SHA=$(image_label "$TARGET_IMAGE" "$CLIENT_LABEL")
validate_full_sha "$TARGET_SERVER_SHA"
validate_full_sha "$TARGET_CLIENT_SHA"

previous_release=$(cat "$RELEASE_ENV")
write_release_env "$TARGET_IMAGE" "$TARGET_SERVER_SHA" "$TARGET_CLIENT_SHA"
if compose_recreate && wait_for_health "$HEALTH_TIMEOUT" && verify_public_api && \
  verify_running_identity "$TARGET_ID" "$TARGET_SERVER_SHA" "$TARGET_CLIENT_SHA"; then
  echo ROLLBACK_SUCCESS
  exit 0
fi

printf '%s\n' "$previous_release" >"$RELEASE_ENV"
chmod 600 "$RELEASE_ENV"
compose_recreate || true
die "rollback target failed health verification; previous release selection restored"
