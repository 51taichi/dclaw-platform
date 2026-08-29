#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

if [ "$#" -ne 5 ]; then
  fail "usage: assemble_context.sh SERVER_DIR CLIENT_DIR OUTPUT_DIR SERVER_SHA CLIENT_SHA"
fi

SERVER_DIR=$1
CLIENT_DIR=$2
OUTPUT_DIR=$3
SERVER_SHA=$4
CLIENT_SHA=$5

test -d "$SERVER_DIR/.git" || fail "server checkout is not a Git repository"
test -d "$CLIENT_DIR/.git" || fail "client checkout is not a Git repository"
test ! -e "$OUTPUT_DIR" || fail "output already exists: $OUTPUT_DIR"

actual_server=$(git -C "$SERVER_DIR" rev-parse HEAD)
actual_client=$(git -C "$CLIENT_DIR" rev-parse HEAD)
test "$actual_server" = "$SERVER_SHA" || fail "server HEAD does not match requested SHA"
test "$actual_client" = "$CLIENT_SHA" || fail "client HEAD does not match requested SHA"

test -f "$SERVER_DIR/deploy/Dockerfile" || fail "deploy/Dockerfile is missing"
test -f "$CLIENT_DIR/console/package-lock.json" || fail "console/package-lock.json is missing"
test -f "$CLIENT_DIR/console/package.json" || fail "console/package.json is missing"
test -d "$CLIENT_DIR/website/public/docs" || fail "website/public/docs is missing"

mkdir -p "$(dirname "$OUTPUT_DIR")"
temporary_output=$(mktemp -d "${OUTPUT_DIR}.tmp.XXXXXX")
cleanup() {
  rm -rf "$temporary_output"
}
trap cleanup EXIT

git -C "$SERVER_DIR" archive "$SERVER_SHA" | tar -x -C "$temporary_output"
mkdir -p "$temporary_output/console"
git -C "$CLIENT_DIR" archive "$CLIENT_SHA" console |
  tar -x --strip-components=1 -C "$temporary_output/console"
git -C "$CLIENT_DIR" archive "$CLIENT_SHA" website/public/docs |
  tar -x -C "$temporary_output"

(
  cd "$temporary_output/console"
  npm ci --include=dev
  npm run build
)

mv "$temporary_output" "$OUTPUT_DIR"
trap - EXIT
