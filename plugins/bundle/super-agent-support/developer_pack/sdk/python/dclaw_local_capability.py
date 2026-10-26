"""Small public helper for deterministic local capability entrypoints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run_json_task(handler: Callable[[dict], dict], request_path: Path) -> dict:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("local capability request must be an object")
    result = handler(request)
    if not isinstance(result, dict):
        raise ValueError("local capability result must be an object")
    return result
