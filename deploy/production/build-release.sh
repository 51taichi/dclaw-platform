#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=${DCLAW_DEPLOY_ROOT:-/opt/dclaw-deploy}
REPOSITORY=51taichi/dclaw-server
WORKFLOW=dclaw-combined-image.yml
IMAGE_REPOSITORY=ghcr.io/51taichi/dclaw
DISCOVERY_TIMEOUT=${DCLAW_BUILD_DISCOVERY_TIMEOUT:-60}
DISCOVERY_INTERVAL=${DCLAW_BUILD_DISCOVERY_INTERVAL:-2}
SHA_PATTERN='^[0-9a-f]{40}$'

command -v gh >/dev/null 2>&1 || {
  echo "BUILD_FAILED"
  echo "reason：GitHub CLI is not installed"
  exit 1
}
gh auth status --hostname github.com >/dev/null 2>&1 || {
  echo "BUILD_FAILED"
  echo "reason：GitHub CLI is not authenticated"
  exit 1
}

mkdir -p "$DEPLOY_ROOT/logs"
chmod 700 "$DEPLOY_ROOT" "$DEPLOY_ROOT/logs"
timestamp=$(date +%Y%m%d-%H%M%S)
log_file="$DEPLOY_ROOT/logs/build-$timestamp.log"
before_file=$(mktemp "$DEPLOY_ROOT/build-before.XXXXXX")
after_file=$(mktemp "$DEPLOY_ROOT/build-after.XXXXXX")
trap 'rm -f "$before_file" "$after_file"' EXIT
chmod 600 "$before_file" "$after_file"

SERVER_SHA=$(gh api repos/51taichi/dclaw-server/commits/main --jq .sha)
CLIENT_SHA=$(gh api repos/51taichi/dclaw-client/commits/main --jq .sha)
[[ $SERVER_SHA =~ $SHA_PATTERN ]] || exit 1
[[ $CLIENT_SHA =~ $SHA_PATTERN ]] || exit 1

gh run list \
  --repo "$REPOSITORY" \
  --workflow "$WORKFLOW" \
  --event workflow_dispatch \
  --limit 20 \
  --json databaseId >"$before_file"

gh workflow run "$WORKFLOW" \
  --repo "$REPOSITORY" \
  --field "server_sha=$SERVER_SHA" \
  --field "client_sha=$CLIENT_SHA" \
  >"$log_file" 2>&1

RUN_ID=
started=$SECONDS
while ((SECONDS - started < DISCOVERY_TIMEOUT)); do
  gh run list \
    --repo "$REPOSITORY" \
    --workflow "$WORKFLOW" \
    --event workflow_dispatch \
    --limit 20 \
    --json databaseId >"$after_file"
  RUN_ID=$(python3 - "$before_file" "$after_file" <<'PY'
import json
import sys

before = {int(row["databaseId"]) for row in json.load(open(sys.argv[1]))}
after = [int(row["databaseId"]) for row in json.load(open(sys.argv[2]))]
print(next((value for value in after if value not in before), ""))
PY
  )
  test -z "$RUN_ID" || break
  sleep "$DISCOVERY_INTERVAL"
done

if test -z "$RUN_ID"; then
  echo "BUILD_FAILED"
  echo "reason：workflow run was not discovered"
  exit 1
fi

if ! gh run watch "$RUN_ID" \
  --repo "$REPOSITORY" \
  --exit-status >>"$log_file" 2>&1; then
  echo "BUILD_FAILED"
  printf 'server/main：%s\n' "${SERVER_SHA:0:7}"
  printf 'client/main：%s\n' "${CLIENT_SHA:0:7}"
  printf 'run：https://github.com/%s/actions/runs/%s\n' \
    "$REPOSITORY" "$RUN_ID"
  exit 1
fi

IMAGE_TAG="$IMAGE_REPOSITORY:server-${SERVER_SHA:0:12}-client-${CLIENT_SHA:0:12}"
pending_tmp=$(mktemp "$DEPLOY_ROOT/pending-release.env.tmp.XXXXXX")
{
  printf 'SERVER_SHA=%s\n' "$SERVER_SHA"
  printf 'CLIENT_SHA=%s\n' "$CLIENT_SHA"
  printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG"
  printf 'BUILD_RUN_ID=%s\n' "$RUN_ID"
  printf 'BUILD_LOG=%s\n' "$log_file"
} >"$pending_tmp"
chmod 600 "$pending_tmp" "$log_file"
mv "$pending_tmp" "$DEPLOY_ROOT/pending-release.env"

echo "BUILD_SUCCESS"
printf 'server/main：%s\n' "${SERVER_SHA:0:7}"
printf 'client/main：%s\n' "${CLIENT_SHA:0:7}"
printf 'image：%s\n' "$IMAGE_TAG"
