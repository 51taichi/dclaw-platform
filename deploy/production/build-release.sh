#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=${DCLAW_DEPLOY_ROOT:-/opt/dclaw-deploy}
SERVER_REPOSITORY=${DCLAW_SERVER_REPOSITORY:-https://github.com/51taichi/dclaw-server.git}
CLIENT_REPOSITORY=${DCLAW_CLIENT_REPOSITORY:-https://github.com/51taichi/dclaw-client.git}
LOCAL_IMAGE_REPOSITORY=${DCLAW_LOCAL_IMAGE_REPOSITORY:-dclaw-local}
SHA_PATTERN='^[0-9a-f]{40}$'
BUILD_NETWORK_ATTEMPTS=${DCLAW_BUILD_NETWORK_ATTEMPTS:-3}
BUILD_RETRY_DELAY_SECONDS=${DCLAW_BUILD_RETRY_DELAY_SECONDS:-5}

fail() {
  echo "BUILD_FAILED"
  printf 'reason：%s\n' "$1"
  exit 1
}

for command in gh git docker flock; do
  command -v "$command" >/dev/null 2>&1 || fail "$command is not installed"
done
gh auth status --hostname github.com >/dev/null 2>&1 ||
  fail "GitHub CLI is not authenticated"

mkdir -p "$DEPLOY_ROOT/logs" "$DEPLOY_ROOT/build-sources"
chmod 700 "$DEPLOY_ROOT" "$DEPLOY_ROOT/logs" "$DEPLOY_ROOT/build-sources"
exec 9>"$DEPLOY_ROOT/build-release.lock"
flock -n 9 || fail "another local build is already running"
rm -f "$DEPLOY_ROOT/pending-release.env"

timestamp=$(date +%Y%m%d-%H%M%S)
log_file="$DEPLOY_ROOT/logs/build-$timestamp.log"
context_dir=$(mktemp -d "$DEPLOY_ROOT/build-context.XXXXXX")
trap 'rm -rf "$context_dir"' EXIT
chmod 700 "$context_dir"

SERVER_DIR="$DEPLOY_ROOT/build-sources/server"
CLIENT_DIR="$DEPLOY_ROOT/build-sources/client"

retry_network_command() {
  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi
    if ((attempt >= BUILD_NETWORK_ATTEMPTS)); then
      return 1
    fi
    printf 'network command failed; retrying (%s/%s): %s\n' \
      "$attempt" "$BUILD_NETWORK_ATTEMPTS" "$*" >&2
    sleep "$BUILD_RETRY_DELAY_SECONDS"
    attempt=$((attempt + 1))
  done
}

sync_checkout() {
  local repository=$1
  local directory=$2
  if test ! -d "$directory/.git"; then
    test ! -e "$directory" || return 1
    git clone --no-checkout "$repository" "$directory"
  fi
  git -C "$directory" remote set-url origin "$repository"
  local revision
  revision=$(retry_network_command git ls-remote \
    "$repository" refs/heads/main | awk 'NR == 1 { print $1 }')
  [[ $revision =~ $SHA_PATTERN ]] || return 1
  retry_network_command git -C "$directory" fetch \
    --force --prune origin "$revision"
  git -C "$directory" checkout --detach --force "$revision"
  test "$(git -C "$directory" rev-parse HEAD)" = "$revision" || return 1
  printf '%s\n' "$revision"
}

build_local_release() {
  gh auth setup-git --hostname github.com || return 1
  SERVER_SHA=$(sync_checkout "$SERVER_REPOSITORY" "$SERVER_DIR") || return 1
  CLIENT_SHA=$(sync_checkout "$CLIENT_REPOSITORY" "$CLIENT_DIR") || return 1
  [[ $SERVER_SHA =~ $SHA_PATTERN ]] || return 1
  [[ $CLIENT_SHA =~ $SHA_PATTERN ]] || return 1

  "$SERVER_DIR/scripts/release/assemble_context.sh" \
    "$SERVER_DIR" "$CLIENT_DIR" "$context_dir/release" \
    "$SERVER_SHA" "$CLIENT_SHA" || return 1

  IMAGE_TAG="$LOCAL_IMAGE_REPOSITORY:server-${SERVER_SHA:0:12}-client-${CLIENT_SHA:0:12}"
  docker build \
    --label "cn.deepmega.dclaw.server-revision=$SERVER_SHA" \
    --label "cn.deepmega.dclaw.client-revision=$CLIENT_SHA" \
    --tag "$IMAGE_TAG" \
    --file "$context_dir/release/deploy/Dockerfile" \
    "$context_dir/release" || return 1

  test "$(docker image inspect "$IMAGE_TAG" --format \
    '{{index .Config.Labels "cn.deepmega.dclaw.server-revision"}}')" = "$SERVER_SHA" || return 1
  test "$(docker image inspect "$IMAGE_TAG" --format \
    '{{index .Config.Labels "cn.deepmega.dclaw.client-revision"}}')" = "$CLIENT_SHA"
  IMAGE_ID=$(docker image inspect "$IMAGE_TAG" --format '{{.Id}}') || return 1
  [[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ ]]
}

if ! build_local_release >"$log_file" 2>&1; then
  chmod 600 "$log_file"
  fail "local image build failed; log=$log_file"
fi

pending_tmp=$(mktemp "$DEPLOY_ROOT/pending-release.env.tmp.XXXXXX")
{
  printf 'SERVER_SHA=%s\n' "$SERVER_SHA"
  printf 'CLIENT_SHA=%s\n' "$CLIENT_SHA"
  printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG"
  printf 'IMAGE_ID=%s\n' "$IMAGE_ID"
  printf 'BUILD_LOG=%s\n' "$log_file"
} >"$pending_tmp"
chmod 600 "$pending_tmp" "$log_file"
mv "$pending_tmp" "$DEPLOY_ROOT/pending-release.env"

echo "BUILD_SUCCESS"
printf 'server/main：%s\n' "${SERVER_SHA:0:7}"
printf 'client/main：%s\n' "${CLIENT_SHA:0:7}"
printf 'image：%s\n' "$IMAGE_TAG"
