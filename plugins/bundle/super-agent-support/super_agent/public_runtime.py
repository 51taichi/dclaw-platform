"""Fail-closed bubblewrap boundary for self-service Super Experts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_HOST_CALLS = 128


class PublicRuntimeError(RuntimeError):
    pass


async def invoke_public_runtime(
    *,
    source_root: Path,
    entrypoint: str,
    request: Any,
    host: Any,
    timeout_seconds: float,
    bwrap_path: Path = Path("/usr/bin/bwrap"),
) -> None:
    if not bwrap_path.is_file():
        raise PublicRuntimeError("runtime_isolation_unavailable")
    source_root = source_root.resolve(strict=True)
    transaction_root = Path(request.transaction_root).resolve(strict=True)
    state_root = Path(request.state_root)
    worker = Path(__file__).with_name("public_worker.py").resolve(strict=True)
    command = [
        str(bwrap_path), "--die-with-parent", "--unshare-all",
        "--unshare-net", "--new-session", "--ro-bind", "/usr", "/usr",
    ]
    for path in ("/lib", "/lib64"):
        if Path(path).exists():
            command.extend(("--ro-bind", path, path))
    command.extend((
        "--dir", "/runtime", "--ro-bind", str(worker), "/runtime/worker.py",
        "--ro-bind", str(source_root), "/release",
        "--bind", str(transaction_root), "/transaction",
    ))
    command.extend(
        ("--ro-bind", str(state_root.resolve()), "/state")
        if state_root.is_dir() else ("--dir", "/state"),
    )
    command.extend((
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--chdir", "/transaction", "/usr/bin/python3", "-I",
        "/runtime/worker.py", "--release-root", "/release",
        "--entrypoint", entrypoint,
    ))
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
            limit=MAX_LINE_BYTES + 1,
            start_new_session=True,
        )
    except OSError as exc:
        raise PublicRuntimeError("runtime_isolation_unavailable") from exc
    try:
        if process.stdin is None or process.stdout is None:
            raise PublicRuntimeError("runtime_isolation_unavailable")
        payload = json.dumps(
            {"type": "start", "request": request.model_dump(mode="json")},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_LINE_BYTES:
            raise PublicRuntimeError("runtime_request_too_large")
        process.stdin.write(payload + b"\n")
        await process.stdin.drain()
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        calls = 0
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise PublicRuntimeError("runtime_timeout")
            line = await asyncio.wait_for(process.stdout.readline(), remaining)
            if not line or len(line) > MAX_LINE_BYTES:
                raise PublicRuntimeError("runtime_protocol_error")
            try:
                message = json.loads(line)
            except ValueError as exc:
                raise PublicRuntimeError("runtime_protocol_error") from exc
            if not isinstance(message, dict):
                raise PublicRuntimeError("runtime_protocol_error")
            if message.get("type") == "done":
                remaining = max(0.01, deadline - asyncio.get_running_loop().time())
                if await asyncio.wait_for(process.wait(), remaining) != 0:
                    raise PublicRuntimeError("runtime_failed")
                return
            if message.get("type") != "call" or not isinstance(message.get("arguments"), dict):
                raise PublicRuntimeError("runtime_protocol_error")
            calls += 1
            if calls > MAX_HOST_CALLS:
                raise PublicRuntimeError("runtime_call_limit")
            try:
                value = await host.call(
                    message.get("capability"), message["arguments"],
                )
                response = json.dumps(
                    {"type": "result", "ok": True, "value": value},
                    ensure_ascii=False,
                ).encode("utf-8")
            except Exception as exc:
                response = json.dumps({
                    "type": "result", "ok": False,
                    "error_code": str(getattr(exc, "error_code", "host_call_failed")),
                }).encode("utf-8")
            if len(response) > MAX_LINE_BYTES:
                raise PublicRuntimeError("runtime_response_too_large")
            process.stdin.write(response + b"\n")
            await process.stdin.drain()
    except (asyncio.TimeoutError, asyncio.LimitOverrunError) as exc:
        raise PublicRuntimeError("runtime_timeout") from exc
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
