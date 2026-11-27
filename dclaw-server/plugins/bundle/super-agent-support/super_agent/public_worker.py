"""Execute developer-owned runtime code inside the plugin sandbox."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import resource
import sys
from pathlib import Path
from types import SimpleNamespace

MAX_LINE_BYTES = 8 * 1024 * 1024


def _send(payload: dict) -> None:
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_LINE_BYTES:
        raise ValueError("sandbox message too large")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


class Host:
    async def call(self, capability: str, arguments: dict) -> object:
        if not isinstance(capability, str) or not isinstance(arguments, dict):
            raise ValueError("invalid host call")
        _send({"type": "call", "capability": capability, "arguments": arguments})
        line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
        if not line or len(line) > MAX_LINE_BYTES:
            raise ValueError("host response unavailable")
        response = json.loads(line)
        if not isinstance(response, dict) or response.get("type") != "result":
            raise ValueError("invalid host response")
        if response.get("ok") is not True:
            raise ValueError(str(response.get("error_code") or "host_call_failed"))
        return response.get("value")


def _load_runtime(root: Path, entrypoint: str):
    module_path, factory_name = entrypoint.split(":", 1)
    candidate = root / module_path
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or candidate.is_symlink():
        raise ValueError("invalid runtime entrypoint")
    sys.path.insert(0, str(resolved_root))
    spec = importlib.util.spec_from_file_location("publisher_runtime", resolved)
    if spec is None or spec.loader is None:
        raise ValueError("invalid runtime entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = getattr(module, factory_name)()
    if not callable(getattr(runtime, "handle", None)):
        raise ValueError("invalid runtime handler")
    return runtime


def _set_limits() -> None:
    for kind, requested in (
        (resource.RLIMIT_AS, 512 * 1024 * 1024),
        (resource.RLIMIT_CPU, 60),
        (resource.RLIMIT_NOFILE, 32),
    ):
        _, hard = resource.getrlimit(kind)
        target = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        resource.setrlimit(kind, (target, target))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


async def _run(root: Path, entrypoint: str) -> None:
    line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
    if not line or len(line) > MAX_LINE_BYTES:
        raise ValueError("runtime request unavailable")
    payload = json.loads(line)
    if not isinstance(payload, dict) or payload.get("type") != "start":
        raise ValueError("invalid runtime request")
    fields = payload.get("request")
    if not isinstance(fields, dict):
        raise ValueError("invalid runtime request")
    fields["state_root"] = Path("/state")
    fields["transaction_root"] = Path("/transaction")
    runtime = _load_runtime(root, entrypoint)
    result = runtime.handle(SimpleNamespace(**fields), Host())
    if not asyncio.iscoroutine(result):
        raise ValueError("runtime handler must be async")
    await result
    _send({"type": "done"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--entrypoint", required=True)
    args = parser.parse_args()
    _set_limits()
    try:
        asyncio.run(_run(args.release_root, args.entrypoint))
    except BaseException:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
