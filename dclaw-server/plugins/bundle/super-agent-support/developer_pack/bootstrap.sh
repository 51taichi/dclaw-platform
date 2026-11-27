#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON:-}
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (3, 14)))' >/dev/null 2>&1; then
      PYTHON_BIN=$candidate
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  printf '%s\n' "CPython 3.10-3.13 is required." >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT/dclaw_developer.py" doctor
"$PYTHON_BIN" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-index \
  --find-links "$ROOT/devkit/wheelhouse" \
  --require-hashes \
  -r "$ROOT/devkit/requirements.lock"
"$ROOT/.venv/bin/python" "$ROOT/devkit/dclaw_agent_devkit.py" doctor
"$ROOT/.venv/bin/python" "$ROOT/dclaw_developer.py" doctor
printf '%s\n' "Developer pack ready: $ROOT/.venv/bin/python"
