"""Generic JSON-lines contract for trusted sealed package entrypoints."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Self

from .harness_protocol import minimal_worker_environment
from .runtime import PinnedSealedRuntime

PROTOCOL_VERSION = "1"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
HostCapability = Literal["agent.execute"]
MAX_HOST_CALLS = 64
DEFAULT_CALL_TIMEOUT_SECONDS = 120.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 300.0
EXECUTION_MODE_ENV = "QWENPAW_SEALED_ENTRYPOINT_EXECUTION_MODE"


class EntrypointProtocolError(RuntimeError):
    """A public-safe sealed entrypoint transport failure."""


class EntrypointTimeout(EntrypointProtocolError):
    pass


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReleaseIdentity(StrictMessage):
    release_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SessionIdentity(StrictMessage):
    conversation_id: str = Field(min_length=1, max_length=512)
    user_id: str = Field(min_length=1, max_length=256)
    channel: str = Field(min_length=1, max_length=256)


class RuntimeInput(StrictMessage):
    role: Literal["user"] = "user"
    content: str = Field(max_length=200_000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeOptions(StrictMessage):
    diagnostics_authorized: bool = False
    capabilities: list[HostCapability] = Field(default_factory=list)


class RuntimeInvoke(StrictMessage):
    type: Literal["runtime.invoke"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    release: ReleaseIdentity
    session: SessionIdentity
    input: RuntimeInput
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    runtime: RuntimeOptions


class RuntimeHandshake(StrictMessage):
    type: Literal["runtime.handshake"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)


class RuntimeReady(StrictMessage):
    type: Literal["runtime.ready"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    adapter: Literal["sealed_entrypoint"]
    contract_version: Literal["1"]


class HostCall(StrictMessage):
    type: Literal["host.call"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=128)
    capability: HostCapability
    arguments: dict[str, Any] = Field(default_factory=dict)


class HostResult(StrictMessage):
    type: Literal["host.result"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=128)
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=128)


class RuntimeFinal(StrictMessage):
    type: Literal["runtime.final"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    reply: str = Field(min_length=1, max_length=500_000)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] | None = None


HostHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
CommandBuilder = Callable[[PinnedSealedRuntime, Path], list[str]]


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max(
            (_json_depth(item, depth + 1) for item in value.values()),
            default=depth,
        )
    if isinstance(value, list):
        return max(
            (_json_depth(item, depth + 1) for item in value),
            default=depth,
        )
    return depth


def validate_protocol_message(encoded: bytes) -> dict[str, Any]:
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("sealed entrypoint message is too large")
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise TypeError("sealed entrypoint message must be an object")
    if _json_depth(value) > MAX_JSON_DEPTH:
        raise ValueError("sealed entrypoint message is too deeply nested")
    return value


@dataclass
class SealedEntrypointProcess:
    pinned: PinnedSealedRuntime
    session_root: Path
    command_builder: CommandBuilder | None = None
    call_timeout_seconds: float = DEFAULT_CALL_TIMEOUT_SECONDS
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS
    bwrap_path: str = "/usr/bin/bwrap"

    def __post_init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._stderr_task: asyncio.Task[bytes] | None = None
        self._completed = False

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def _runtime_paths(self) -> tuple[Path, Path]:
        release_root = self.pinned.release_root.resolve()
        entrypoint = (release_root / self.pinned.entrypoint).resolve()
        if (
            not entrypoint.is_relative_to(release_root)
            or entrypoint.is_symlink()
            or not entrypoint.is_file()
        ):
            raise EntrypointProtocolError("sealed runtime entrypoint is unsafe")
        worker = Path(__file__).with_name("entrypoint_worker.py").resolve()
        return release_root, worker

    def _trusted_direct_command(self) -> list[str]:
        release_root, worker = self._runtime_paths()
        return [
            sys.executable,
            "-I",
            str(worker),
            "--release-root",
            str(release_root),
            "--session-root",
            str(self.session_root.resolve()),
            "--entrypoint",
            self.pinned.entrypoint,
        ]

    def _bubblewrap_command(self) -> list[str]:
        if not Path(self.bwrap_path).is_file():
            raise EntrypointProtocolError("sealed runtime isolation is unavailable")
        release_root, worker = self._runtime_paths()
        command = [
            self.bwrap_path,
            "--die-with-parent",
            "--unshare-all",
            "--unshare-net",
            "--new-session",
            "--ro-bind",
            "/usr",
            "/usr",
        ]
        for library_root in ("/lib", "/lib64"):
            if Path(library_root).exists():
                command.extend(["--ro-bind", library_root, library_root])
        command.extend(
            [
                "--dir",
                "/runtime",
                "--ro-bind",
                str(worker),
                "/runtime/entrypoint_worker.py",
                "--ro-bind",
                str(release_root),
                "/release",
                "--bind",
                str(self.session_root.resolve()),
                "/session",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "/usr/bin/python3",
                "-I",
                "/runtime/entrypoint_worker.py",
                "--release-root",
                "/release",
                "--session-root",
                "/session",
                "--entrypoint",
                self.pinned.entrypoint,
            ],
        )
        return command

    def _default_command(self) -> list[str]:
        mode = os.environ.get(EXECUTION_MODE_ENV, "bubblewrap").strip()
        if mode == "trusted_direct":
            return self._trusted_direct_command()
        if mode == "bubblewrap":
            return self._bubblewrap_command()
        raise EntrypointProtocolError("sealed entrypoint execution mode is invalid")

    async def start(self) -> None:
        if self._process is not None:
            return
        self.session_root.mkdir(parents=True, exist_ok=True)
        command = (
            self.command_builder(self.pinned, self.session_root)
            if self.command_builder is not None
            else self._default_command()
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=minimal_worker_environment(),
                start_new_session=True,
            )
        except Exception as exc:
            await self.close()
            raise EntrypointProtocolError(
                "sealed entrypoint isolation failed",
            ) from exc
        self._started_at = asyncio.get_running_loop().time()
        self._stderr_task = asyncio.create_task(self._capture_stderr())

    async def handshake(self) -> RuntimeReady:
        request = RuntimeHandshake(
            type="runtime.handshake",
            protocol_version="1",
            invocation_id="runtime-validation",
            message_id="handshake",
        )
        raw = await self._exchange_initial(request.model_dump(mode="json"))
        try:
            ready = RuntimeReady.model_validate(raw)
        except Exception as exc:
            raise EntrypointProtocolError(
                "sealed entrypoint handshake is invalid",
            ) from exc
        await self._finish_once()
        return ready

    async def invoke(
        self,
        request: RuntimeInvoke,
        host_handler: HostHandler,
    ) -> RuntimeFinal:
        if self._completed:
            raise EntrypointProtocolError("sealed entrypoint already completed")
        await self._write(request.model_dump(mode="json"))
        call_count = 0
        while True:
            raw = await self._read()
            message_type = raw.get("type")
            if message_type == "host.call":
                call_count += 1
                if call_count > MAX_HOST_CALLS:
                    raise EntrypointProtocolError(
                        "sealed entrypoint host call limit exceeded",
                    )
                try:
                    call = HostCall.model_validate(raw)
                except Exception as exc:
                    raise EntrypointProtocolError(
                        "sealed entrypoint host call is invalid",
                    ) from exc
                if call.invocation_id != request.invocation_id:
                    raise EntrypointProtocolError(
                        "sealed entrypoint invocation identity mismatch",
                    )
                try:
                    result = await host_handler(call.capability, call.arguments)
                    response = HostResult(
                        type="host.result",
                        protocol_version="1",
                        invocation_id=call.invocation_id,
                        call_id=call.call_id,
                        ok=True,
                        result=result,
                    )
                except Exception:  # noqa: BLE001 - host failures fail closed
                    response = HostResult(
                        type="host.result",
                        protocol_version="1",
                        invocation_id=call.invocation_id,
                        call_id=call.call_id,
                        ok=False,
                        error_code="host_call_failed",
                    )
                await self._write(response.model_dump(mode="json"))
                continue
            if message_type == "runtime.error":
                raise EntrypointProtocolError("sealed entrypoint execution failed")
            if message_type != "runtime.final":
                raise EntrypointProtocolError(
                    "sealed entrypoint response is invalid",
                )
            try:
                final = RuntimeFinal.model_validate(raw)
            except Exception as exc:
                raise EntrypointProtocolError(
                    "sealed entrypoint final response is invalid",
                ) from exc
            if final.invocation_id != request.invocation_id:
                raise EntrypointProtocolError(
                    "sealed entrypoint invocation identity mismatch",
                )
            await self._finish_once()
            return final

    async def _exchange_initial(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._completed:
            raise EntrypointProtocolError("sealed entrypoint already completed")
        await self._write(payload)
        raw = await self._read()
        if raw.get("type") == "runtime.error":
            raise EntrypointProtocolError("sealed entrypoint execution failed")
        return raw

    async def _write(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise EntrypointProtocolError("sealed entrypoint is not running")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        validate_protocol_message(encoded)
        process.stdin.write(encoded + b"\n")
        try:
            await process.stdin.drain()
        except Exception as exc:
            raise EntrypointProtocolError(
                "sealed entrypoint transport failed",
            ) from exc

    async def _read(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise EntrypointProtocolError("sealed entrypoint is not running")
        if self._started_at is None:
            raise EntrypointProtocolError("sealed entrypoint clock is unavailable")
        elapsed = asyncio.get_running_loop().time() - self._started_at
        remaining = self.total_timeout_seconds - elapsed
        if remaining <= 0:
            raise EntrypointTimeout("sealed entrypoint total timeout")
        try:
            line = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=min(self.call_timeout_seconds, remaining),
            )
        except asyncio.TimeoutError as exc:
            raise EntrypointTimeout("sealed entrypoint call timeout") from exc
        if not line:
            raise EntrypointProtocolError("sealed entrypoint closed unexpectedly")
        try:
            return validate_protocol_message(line.rstrip(b"\n"))
        except Exception as exc:
            raise EntrypointProtocolError(
                "sealed entrypoint response is malformed",
            ) from exc

    async def _finish_once(self) -> None:
        process = self._process
        if process is None:
            raise EntrypointProtocolError("sealed entrypoint is not running")
        self._completed = True
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError as exc:
            raise EntrypointProtocolError(
                "sealed entrypoint did not terminate",
            ) from exc
        if process.stdout is not None:
            extra = await process.stdout.read(MAX_MESSAGE_BYTES + 1)
            if extra.strip():
                raise EntrypointProtocolError(
                    "sealed entrypoint returned multiple final messages",
                )
        if process.returncode != 0:
            raise EntrypointProtocolError("sealed entrypoint execution failed")

    async def _capture_stderr(self) -> bytes:
        process = self._process
        if process is None or process.stderr is None:
            return b""
        data = await process.stderr.read(64 * 1024 + 1)
        return data[: 64 * 1024]

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, 15)
        except (ProcessLookupError, PermissionError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, 9)
            except (ProcessLookupError, PermissionError):
                process.kill()
            await process.wait()

    async def close(self) -> None:
        await self._terminate()
        if self._stderr_task is not None:
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        self._process = None
