"""Bounded JSON-lines transport for isolated sealed harnesses."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .runtime import PinnedSealedRuntime

MAX_MESSAGE_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_STDERR_BYTES = 64 * 1024
DEFAULT_STAGE_TIMEOUT_SECONDS = 30.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 300.0


class HarnessProtocolError(RuntimeError):
    """The isolated worker violated its trusted transport contract."""


class HarnessTimeout(HarnessProtocolError):
    pass


class HarnessStageError(HarnessProtocolError):
    def __init__(self, error_code: str) -> None:
        super().__init__("sealed harness stage failed")
        self.error_code = error_code


class HarnessStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    stage: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    payload: dict[str, Any]


class HarnessStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


def minimal_worker_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


@dataclass
class HarnessProcess:
    pinned: PinnedSealedRuntime
    session_root: Path | None = None
    stage_timeout_seconds: float = DEFAULT_STAGE_TIMEOUT_SECONDS
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS
    bwrap_path: str = "/usr/bin/bwrap"

    def __post_init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._temporary_session: Path | None = None
        self._stderr_task: asyncio.Task[bytes] | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "HarnessProcess":
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._process is not None:
            return
        if not Path(self.bwrap_path).is_file():
            raise HarnessProtocolError("sealed runtime isolation is unavailable")
        release_root = self.pinned.release_root.resolve()
        if not release_root.is_dir():
            raise HarnessProtocolError("sealed runtime release is unavailable")
        entrypoint = (release_root / self.pinned.entrypoint).resolve()
        if not entrypoint.is_relative_to(release_root) or entrypoint.is_symlink():
            raise HarnessProtocolError("sealed runtime entrypoint is unsafe")

        if self.session_root is None:
            self._temporary_session = Path(tempfile.mkdtemp(prefix="sealed-harness-"))
            session_root = self._temporary_session
        else:
            session_root = Path(self.session_root)
            session_root.mkdir(parents=True, exist_ok=True)
        worker = Path(__file__).with_name("harness_worker.py").resolve()
        command = [
            self.bwrap_path,
            "--die-with-parent",
            "--unshare-all",
            "--unshare-net",
            "--new-session",
            "--ro-bind", "/usr", "/usr",
        ]
        for system_library_root in ("/lib", "/lib64"):
            if Path(system_library_root).exists():
                command.extend(
                    ["--ro-bind", system_library_root, system_library_root],
                )
        command.extend([
            "--dir", "/runtime",
            "--ro-bind", str(worker), "/runtime/harness_worker.py",
            "--ro-bind", str(release_root), "/release",
            "--bind", str(session_root.resolve()), "/session",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "/usr/bin/python3",
            "-I",
            "/runtime/harness_worker.py",
            "--release-root", "/release",
            "--session-root", "/session",
            "--entrypoint", self.pinned.entrypoint,
        ])
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
            raise HarnessProtocolError("sealed runtime isolation failed") from exc
        self._started_at = asyncio.get_running_loop().time()
        self._stderr_task = asyncio.create_task(self._capture_stderr())

    async def invoke(self, stage: str, payload: dict[str, Any]) -> HarnessStageResponse:
        async with self._lock:
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise HarnessProtocolError("sealed harness is not running")
            if self._started_at is None:
                raise HarnessProtocolError("sealed harness clock is unavailable")
            elapsed = asyncio.get_running_loop().time() - self._started_at
            if elapsed >= self.total_timeout_seconds:
                await self._terminate()
                raise HarnessTimeout("sealed harness total timeout")
            request = HarnessStageRequest(
                request_id=uuid.uuid4().hex,
                stage=stage,
                payload=payload,
            )
            if _json_depth(request.payload) > MAX_JSON_DEPTH:
                raise HarnessProtocolError("sealed harness payload is too deeply nested")
            encoded = (request.model_dump_json() + "\n").encode()
            if len(encoded) > MAX_MESSAGE_BYTES:
                raise HarnessProtocolError("sealed harness request is too large")
            try:
                process.stdin.write(encoded)
                await process.stdin.drain()
                timeout = min(
                    self.stage_timeout_seconds,
                    self.total_timeout_seconds - elapsed,
                )
                line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                await self._terminate()
                raise HarnessTimeout("sealed harness stage timeout") from exc
            except Exception as exc:
                await self._terminate()
                raise HarnessProtocolError("sealed harness transport failed") from exc
            if not line or len(line) > MAX_MESSAGE_BYTES:
                await self._terminate()
                raise HarnessProtocolError("sealed harness response is invalid")
            try:
                raw = json.loads(line)
                if _json_depth(raw) > MAX_JSON_DEPTH:
                    raise ValueError("response nesting")
                response = HarnessStageResponse.model_validate(raw)
            except Exception as exc:
                await self._terminate()
                raise HarnessProtocolError("sealed harness response is malformed") from exc
            if response.request_id != request.request_id:
                await self._terminate()
                raise HarnessProtocolError("sealed harness response identity mismatch")
            if not response.ok:
                raise HarnessStageError(response.error_code or "stage_failed")
            return response

    async def _capture_stderr(self) -> bytes:
        process = self._process
        if process is None or process.stderr is None:
            return b""
        data = await process.stderr.read(MAX_STDERR_BYTES + 1)
        return data[:MAX_STDERR_BYTES]

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
        if self._temporary_session is not None:
            shutil.rmtree(self._temporary_session, ignore_errors=True)
            self._temporary_session = None
