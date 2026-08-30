#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=${DCLAW_DEPLOY_ROOT:-/opt/dclaw-deploy}
RESULT="$DEPLOY_ROOT/latest-deploy-result"

if test ! -s "$RESULT"; then
  echo "NO_DEPLOYMENT_RESULT"
  exit 1
fi
cat "$RESULT"
