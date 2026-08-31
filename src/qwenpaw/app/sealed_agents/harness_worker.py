"""Minimal isolated worker for signed sealed-agent runtime entrypoints."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import sys
from pathlib import Path
from typing import Any

MAX_MESSAGE_BYTES = 1024 * 1024
ALLOWED_STAGES = {
    "handshake",
    "prepare_interaction",
    "controller_gate",
    "required_skill_dispatch",
    "completion_validation",
    "commit",
    "render_bound",
}


def _limits() -> None:
    # macOS reports RLIMIT_AS but rejects lowering it for an already-loaded
    # interpreter. Production is Linux, where this limit is mandatory.
    if sys.platform != "darwin":
        _lower_limit(resource.RLIMIT_AS, 512 * 1024 * 1024)
    _lower_limit(resource.RLIMIT_CPU, 60)
    _lower_limit(resource.RLIMIT_NOFILE, 32)
    if hasattr(resource, "RLIMIT_NPROC"):
        _lower_limit(resource.RLIMIT_NPROC, 0)


def _lower_limit(kind: int, requested: int) -> None:
    _soft, hard = resource.getrlimit(kind)
    target = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
    resource.setrlimit(kind, (target, target))


def _load_harness(release_root: Path, entrypoint: str) -> Any:
    root = release_root.resolve()
    target = (root / entrypoint).resolve()
    if not target.is_relative_to(root) or target.is_symlink() or not target.is_file():
        raise RuntimeError("unsafe_entrypoint")
    spec = importlib.util.spec_from_file_location("sealed_release_entrypoint", target)
    if spec is None or spec.loader is None:
        raise RuntimeError("invalid_entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_harness", None)
    if not callable(factory):
        raise RuntimeError("missing_harness_factory")
    return factory()


def _respond(request_id: str, *, payload: dict[str, Any] | None = None, error: str | None = None) -> None:
    encoded = json.dumps(
        {
            "request_id": request_id,
            "ok": error is None,
            "payload": payload or {},
            "error_code": error,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    if len(encoded) > MAX_MESSAGE_BYTES:
        encoded = json.dumps(
            {"request_id": request_id, "ok": False, "payload": {}, "error_code": "response_too_large"},
            separators=(",", ":"),
        ).encode()
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--session-root", required=True)
    parser.add_argument("--entrypoint", required=True)
    args = parser.parse_args()
    _limits()
    os.chdir(args.session_root)
    try:
        harness = _load_harness(Path(args.release_root), args.entrypoint)
    except Exception:
        return 2
    for line in sys.stdin.buffer:
        if len(line) > MAX_MESSAGE_BYTES:
            return 3
        request_id = "unknown"
        try:
            request = json.loads(line)
            request_id = str(request["request_id"])
            stage = str(request["stage"])
            payload = request["payload"]
            if stage not in ALLOWED_STAGES or not isinstance(payload, dict):
                raise ValueError("invalid_stage")
            method = getattr(harness, stage, None)
            if not callable(method):
                raise ValueError("unsupported_stage")
            result = method(payload)
            if not isinstance(result, dict):
                raise ValueError("invalid_result")
            _respond(request_id, payload=result)
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) else "stage_failed"
            _respond(request_id, error=code[:64])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
