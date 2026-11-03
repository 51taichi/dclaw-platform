"""Plugin-owned Unix-socket broker for isolated developer runtimes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from public_runtime import (
    MAX_LINE_BYTES,
    PublicRuntimeError,
    invoke_public_runtime,
    isolation_available,
)


class RuntimeRequest:
    def __init__(self, fields: dict[str, Any]) -> None:
        self.fields = fields
        self.transaction_root = Path(fields["transaction_root"])
        self.state_root = Path(fields["state_root"])

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        if mode != "json":
            raise ValueError("unsupported runtime serialization")
        return self.fields


class HostRelay:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer

    async def call(self, capability: str, arguments: dict[str, Any]) -> Any:
        payload = json.dumps(
            {"type": "call", "capability": capability,
             "arguments": arguments},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_LINE_BYTES:
            raise PublicRuntimeError("runtime_request_too_large")
        self.writer.write(payload + b"\n")
        await self.writer.drain()
        line = await self.reader.readline()
        if not line or len(line) > MAX_LINE_BYTES:
            raise PublicRuntimeError("runtime_protocol_error")
        message = json.loads(line)
        if not isinstance(message, dict) or message.get("type") != "result":
            raise PublicRuntimeError("runtime_protocol_error")
        if message.get("ok") is not True:
            raise PublicRuntimeError(
                str(message.get("error_code") or "host_call_failed"),
            )
        return message.get("value")


def _shared_path(root: Path, value: Any, *, required: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid shared path")
    path = Path(value).resolve(strict=required)
    if not path.is_relative_to(root):
        raise ValueError("runtime path is outside shared root")
    return path


def _under(path: Path, root: Path) -> Path:
    if not path.is_relative_to(root):
        raise ValueError("runtime path is outside its assigned area")
    return path


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    shared_root: Path,
) -> None:
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        if not line or len(line) > MAX_LINE_BYTES:
            raise ValueError("invalid sandbox request")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("invalid sandbox request")
        if message.get("type") == "health":
            writer.write(b'{"type":"health","available":true}\n')
        elif message.get("type") == "start":
            fields = message.get("request")
            if not isinstance(fields, dict):
                raise ValueError("invalid sandbox request")
            source_root = _under(
                _shared_path(
                    shared_root, message.get("source_root"), required=True,
                ),
                shared_root / "sealed_agents" / "releases",
            )
            fields["transaction_root"] = str(_under(
                _shared_path(
                    shared_root, fields.get("transaction_root"), required=True,
                ),
                shared_root / "workspace_runtime_state" / "transactions",
            ))
            fields["state_root"] = str(_under(
                _shared_path(
                    shared_root, fields.get("state_root"), required=False,
                ),
                shared_root / "workspace_runtime_state" / "state",
            ))
            entrypoint = message.get("entrypoint")
            timeout_seconds = message.get("timeout_seconds")
            if (
                not isinstance(entrypoint, str)
                or not 0 < len(entrypoint) <= 256
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 3600
            ):
                raise ValueError("invalid sandbox request")
            await invoke_public_runtime(
                source_root=source_root, entrypoint=entrypoint,
                request=RuntimeRequest(fields),
                host=HostRelay(reader, writer),
                timeout_seconds=float(timeout_seconds),
                use_sidecar=False,
            )
            writer.write(b'{"type":"done"}\n')
        else:
            raise ValueError("invalid sandbox request")
        await writer.drain()
    except (PublicRuntimeError, ValueError, OSError, asyncio.TimeoutError) as exc:
        code = (
            str(exc) if isinstance(exc, PublicRuntimeError)
            else "runtime_isolation_unavailable"
        )
        try:
            writer.write(json.dumps(
                {"type": "error", "code": code},
                separators=(",", ":"),
            ).encode("utf-8") + b"\n")
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
    finally:
        writer.close()
        await writer.wait_closed()


async def serve(socket_path: Path, shared_root: Path) -> None:
    shared_root = shared_root.resolve(strict=True)
    if not isolation_available(socket_path=""):
        raise RuntimeError("runtime isolation unavailable")
    socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    socket_path.parent.chmod(0o700)
    if socket_path.exists():
        socket_path.unlink()
    server = await asyncio.start_unix_server(
        lambda reader, writer: _handle(reader, writer, shared_root),
        path=str(socket_path), limit=MAX_LINE_BYTES + 1,
    )
    os.chmod(socket_path, 0o600)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--shared-root", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.socket, args.shared_root))


if __name__ == "__main__":
    main()
