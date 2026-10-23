#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$ROOT/.venv"

if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN=$PYTHON
else
  PYTHON_BIN=""
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

"$PYTHON_BIN" "$ROOT/dclaw_agent_devkit.py" doctor --wheelhouse-only
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-index \
  --find-links "$ROOT/wheelhouse" \
  --require-hashes \
  -r "$ROOT/requirements.lock"
"$VENV_DIR/bin/python" "$ROOT/dclaw_agent_devkit.py" doctor

printf '%s\n' "DevKit ready: $VENV_DIR/bin/python"
