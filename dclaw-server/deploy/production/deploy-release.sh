#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=${DCLAW_DEPLOY_ROOT:-/opt/dclaw-deploy}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PENDING="$DEPLOY_ROOT/pending-release.env"
RESULT="$DEPLOY_ROOT/latest-deploy-result"
PID_FILE="$DEPLOY_ROOT/deploy-release.pid"

read_pending() {
  test -s "$PENDING" || {
    echo "ERROR: no successful build is pending" >&2
    exit 1
  }
  SERVER_SHA=
  CLIENT_SHA=
  IMAGE_TAG=
  IMAGE_ID=
  while IFS='=' read -r key value; do
    case "$key" in
      SERVER_SHA) SERVER_SHA=$value ;;
      CLIENT_SHA) CLIENT_SHA=$value ;;
      IMAGE_TAG) IMAGE_TAG=$value ;;
      IMAGE_ID) IMAGE_ID=$value ;;
    esac
  done <"$PENDING"
  [[ $SERVER_SHA =~ ^[0-9a-f]{40}$ ]] || exit 1
  [[ $CLIENT_SHA =~ ^[0-9a-f]{40}$ ]] || exit 1
  test -n "$IMAGE_TAG"
  [[ $IMAGE_TAG =~ ^[a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+$ ]] || exit 1
  [[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ ]] || exit 1
}

write_result() {
  local status=$1
  local temporary
  temporary=$(mktemp "$DEPLOY_ROOT/latest-deploy-result.tmp.XXXXXX")
  {
    printf '%s\n' "$status"
    printf 'server/main：%s\n' "${SERVER_SHA:0:7}"
    printf 'client/main：%s\n' "${CLIENT_SHA:0:7}"
    if test "$status" = UPDATE_SUCCESS; then
      echo "container：running"
      echo "local_api：200"
      echo "public_api：200"
    fi
  } >"$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$RESULT"
}

run_worker() {
  local timestamp log_file
  timestamp=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$DEPLOY_ROOT/logs"
  chmod 700 "$DEPLOY_ROOT/logs"
  log_file="$DEPLOY_ROOT/logs/deploy-$timestamp.log"
  if bash "$SCRIPT_DIR/update.sh" \
    --server-sha "$SERVER_SHA" \
    --client-sha "$CLIENT_SHA" \
    --image "$IMAGE_ID" >"$log_file" 2>&1; then
    chmod 600 "$log_file"
    write_result UPDATE_SUCCESS
    return 0
  fi
  chmod 600 "$log_file"
  if grep -q '^UPDATE_FAILED_ROLLBACK_READY$' "$log_file"; then
    write_result UPDATE_FAILED_ROLLBACK_READY
  else
    write_result UPDATE_FAILED
  fi
  return 1
}

if test "${1:-}" = --worker; then
  test "$#" -eq 4 || exit 1
  SERVER_SHA=$2
  CLIENT_SHA=$3
  IMAGE_ID=$4
  [[ $SERVER_SHA =~ ^[0-9a-f]{40}$ ]] || exit 1
  [[ $CLIENT_SHA =~ ^[0-9a-f]{40}$ ]] || exit 1
  [[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ ]] || exit 1
  run_worker
  exit $?
fi

read_pending

if test -s "$PID_FILE" && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "ERROR: deployment is already running" >&2
  exit 1
fi

write_result UPDATE_RUNNING
if test "${DCLAW_DEPLOY_FOREGROUND:-0}" = 1; then
  run_worker
else
  nohup "$0" --worker "$SERVER_SHA" "$CLIENT_SHA" "$IMAGE_ID" \
    >/dev/null 2>&1 &
  printf '%s\n' "$!" >"$PID_FILE"
  chmod 600 "$PID_FILE"
fi
echo "DEPLOY_STARTED"
