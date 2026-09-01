"""Standalone worker for one trusted sealed-entrypoint invocation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

MAX_MESSAGE_BYTES = 1024 * 1024
MAX_HOST_CALLS = 64


def _lower_limit(kind: int, requested: int) -> None:
    _soft, hard = resource.getrlimit(kind)
    target = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
    resource.setrlimit(kind, (target, target))


def _limits() -> None:
    if sys.platform != "darwin":
        _lower_limit(resource.RLIMIT_AS, 512 * 1024 * 1024)
    _lower_limit(resource.RLIMIT_CPU, 60)
    _lower_limit(resource.RLIMIT_NOFILE, 32)
    if hasattr(resource, "RLIMIT_NPROC"):
        _lower_limit(resource.RLIMIT_NPROC, 0)


def _load_runtime(release_root: Path, entrypoint: str) -> Any:
    root = release_root.resolve()
    target = (root / entrypoint).resolve()
    if not target.is_relative_to(root) or target.is_symlink() or not target.is_file():
        raise RuntimeError("unsafe_entrypoint")
    sys.path.insert(0, str(target.parent))
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("sealed_release_entrypoint", target)
    if spec is None or spec.loader is None:
        raise RuntimeError("invalid_entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_runtime", None)
    if not callable(factory):
        raise TypeError("missing_runtime_factory")
    return factory()


def _read() -> dict[str, Any]:
    line = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
    if not line or len(line) > MAX_MESSAGE_BYTES:
        raise RuntimeError("invalid_message")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise TypeError("invalid_message")
    return value


def _write(value: dict[str, Any]) -> None:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise RuntimeError("response_too_large")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


class HostBridge:
    def __init__(self, invocation_id: str) -> None:
        self.invocation_id = invocation_id
        self.calls = 0

    def call(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls > MAX_HOST_CALLS:
            raise RuntimeError("host_call_limit")
        call_id = uuid.uuid4().hex
        _write(
            {
                "type": "host.call",
                "protocol_version": "1",
                "invocation_id": self.invocation_id,
                "call_id": call_id,
                "capability": capability,
                "arguments": arguments,
            },
        )
        result = _read()
        if (
            result.get("type") != "host.result"
            or result.get("protocol_version") != "1"
            or result.get("invocation_id") != self.invocation_id
            or result.get("call_id") != call_id
        ):
            raise RuntimeError("host_result_mismatch")
        if result.get("ok") is not True:
            raise RuntimeError("host_call_failed")
        payload = result.get("result")
        if not isinstance(payload, dict):
            raise TypeError("host_result_invalid")
        return payload


def _run(runtime: Any, request: dict[str, Any]) -> None:
    invocation_id = str(request.get("invocation_id") or "")
    message_id = str(request.get("message_id") or "")
    if request.get("protocol_version") != "1" or not invocation_id or not message_id:
        raise RuntimeError("invalid_request")
    if request.get("type") == "runtime.handshake":
        handshake = runtime.handshake()
        if not isinstance(handshake, dict):
            raise RuntimeError("invalid_handshake")
        _write(
            {
                "type": "runtime.ready",
                "protocol_version": "1",
                "invocation_id": invocation_id,
                "message_id": message_id,
                "adapter": handshake.get("adapter"),
                "contract_version": handshake.get("contract_version"),
            },
        )
        return
    if request.get("type") != "runtime.invoke":
        raise RuntimeError("invalid_request_type")
    result = runtime.handle(request, HostBridge(invocation_id))
    if not isinstance(result, dict):
        raise TypeError("invalid_runtime_result")
    _write(
        {
            "type": "runtime.final",
            "protocol_version": "1",
            "invocation_id": invocation_id,
            "message_id": uuid.uuid4().hex,
            "reply": result.get("reply"),
            "artifacts": result.get("artifacts", []),
            "diagnostics": result.get("diagnostics"),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--session-root", required=True)
    parser.add_argument("--entrypoint", required=True)
    args = parser.parse_args()
    _limits()
    os.chdir(args.session_root)
    invocation_id = "unknown"
    try:
        runtime = _load_runtime(Path(args.release_root), args.entrypoint)
        request = _read()
        invocation_id = str(request.get("invocation_id") or invocation_id)
        _run(runtime, request)
        return 0
    except Exception:  # noqa: BLE001 - worker errors are deliberately opaque
        with suppress(Exception):
            _write(
                {
                    "type": "runtime.error",
                    "protocol_version": "1",
                    "invocation_id": invocation_id,
                    "error_code": "sealed_entrypoint_failed",
                },
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
