#!/usr/bin/env bash
# Release DClaw desktop artifacts to domestic OSS. Run from repo root.
set -euo pipefail

python3 "$(cd "$(dirname "$0")" && pwd)/desktop_release.py" "$@"
