"""Minimal deterministic local capability used by the offline simulator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


def execute(request: dict, task_root: Path) -> dict:
    text = str(request.get("text", "")).strip()
    if not text:
        raise ValueError("text is required")
    task_root.mkdir(parents=True, exist_ok=True)
    output = task_root / "result.txt"
    output.write_text(text.upper() + "\n", encoding="utf-8")
    return {
        "output": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    if len(sys.argv) == 3:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        task_root = Path(sys.argv[2])
    else:
        request = {"text": "dclaw local capability"}
        task_root = Path(".demo-task")
    print(json.dumps({"status": "succeeded", "result": execute(request, task_root)}))
