"""Generic, fail-closed execution of Agent-owned workspace runtimes."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from qwenpaw.config.config import OrchestrationConfig
from qwenpaw.app.sealed_agents.models import SealedAgentRecord
from qwenpaw.app.sealed_agents.registry import get_sealed_agent_registry
from qwenpaw.app.sealed_agents.package import (
    SealedPackageError,
    inspect_extracted_payload,
)
from qwenpaw.app.super_experts.grants import SuperExpertGrantRepository
from qwenpaw.constant import WORKING_DIR
from agentscope.message import Msg

from .orchestration_contract import (
    WorkspaceTurnCompletion,
    WorkspaceTurnFailure,
    WorkspaceTurnRequest,
)

logger = logging.getLogger(__name__)


class WorkspaceOrchestrationError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class WorkspaceTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class AuthorizedWorkspaceRelease:
    installation_id: str
    release_id: str
    release_digest: str
    granted_capabilities: dict[str, str]
    signed_workspace_files: frozenset[str]


def authorize_workspace_release(
    *,
    record: SealedAgentRecord,
    workspace_root: Path,
    release_root: Path,
    grant_repository: SuperExpertGrantRepository,
    tenant_id: str,
    config: OrchestrationConfig,
) -> AuthorizedWorkspaceRelease:
    release = record.active_release
    if (
        release is None
        or release.state != "active"
        or release.package_type != "super_expert"
        or release.orchestration_capability_id != "workspace.turn.orchestrate/1"
        or release.orchestration_contract_version != config.contract_version
        or release.orchestration_entrypoint != config.entrypoint
        or set(release.orchestration_required_host_capabilities)
        != set(config.required_host_capabilities)
    ):
        raise WorkspaceOrchestrationError("unauthorized_capability")
    expected_workspace = (Path(release_root) / "agent").resolve(strict=True)
    if Path(workspace_root).resolve(strict=True) != expected_workspace:
        raise WorkspaceOrchestrationError("unauthorized_capability")
    try:
        actual_digest, signed_files = inspect_extracted_payload(release_root)
    except (OSError, SealedPackageError) as exc:
        raise WorkspaceOrchestrationError("orchestration_error") from exc
    if actual_digest != release.content_digest:
        raise WorkspaceOrchestrationError("orchestration_error")
    declared = dict(release.declared_capabilities)
    if declared.get("workspace.turn.orchestrate/1") != config.contract_version:
        raise WorkspaceOrchestrationError("unauthorized_capability")
    if any(
        declared.get(capability) != "1"
        for capability in config.required_host_capabilities
    ):
        raise WorkspaceOrchestrationError("unauthorized_capability")
    grant = grant_repository.find_release_grant(
        record.agent_id,
        release,
        tenant_id=tenant_id,
    )
    if grant is None:
        raise WorkspaceOrchestrationError("unauthorized_capability")
    workspace_files = frozenset(
        path.removeprefix("agent/")
        for path in signed_files
        if path.startswith("agent/")
    )
    module_path = config.entrypoint.split(":", 1)[0]
    if module_path not in workspace_files:
        raise WorkspaceOrchestrationError("orchestration_error")
    return AuthorizedWorkspaceRelease(
        installation_id=grant.installation_id,
        release_id=release.release_id,
        release_digest=release.content_digest,
        granted_capabilities=dict(grant.capabilities),
        signed_workspace_files=workspace_files,
    )


def resolve_active_workspace_authorization(
    *,
    agent_id: str,
    workspace_root: Path,
    tenant_id: str,
    config: OrchestrationConfig,
) -> AuthorizedWorkspaceRelease:
    record = get_sealed_agent_registry().get_agent(agent_id)
    if record is None or record.active_release_id is None:
        raise WorkspaceOrchestrationError("unauthorized_capability")
    sealed_root = Path(WORKING_DIR) / "sealed_agents"
    release_root = (
        sealed_root / "releases" / agent_id / record.active_release_id
    )
    return authorize_workspace_release(
        record=record,
        workspace_root=workspace_root,
        release_root=release_root,
        grant_repository=SuperExpertGrantRepository(sealed_root),
        tenant_id=tenant_id,
        config=config,
    )


def workspace_result_to_message(
    result: WorkspaceTurnResult,
    *,
    agent_name: str,
) -> Msg:
    if result.error_code is not None or result.message is None:
        return Msg(
            name=agent_name,
            role="assistant",
            content="本轮处理未能安全完成，请稍后重试。",
        )
    message = result.message
    if {"name", "role", "content"}.issubset(message):
        try:
            return Msg.from_dict(message)
        except Exception as exc:
            raise WorkspaceOrchestrationError("invalid_completion") from exc
    if isinstance(message.get("reply"), str):
        return Msg(
            name=agent_name,
            role="assistant",
            content=message["reply"],
        )
    raise WorkspaceOrchestrationError("invalid_completion")


def _validate_render_bound_message(message: dict[str, Any]) -> None:
    if {"name", "role", "content"}.issubset(message):
        if message["role"] != "assistant" or not isinstance(message["name"], str):
            raise WorkspaceOrchestrationError("invalid_completion")
        return
    if isinstance(message.get("reply"), str):
        return
    raise WorkspaceOrchestrationError("invalid_completion")


def _scope_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def runtime_trace_path(
    storage_root: Path,
    *,
    installation_id: str,
    session_id: str,
) -> Path:
    return (
        Path(storage_root)
        / "traces"
        / _scope_key(installation_id)
        / f"{_scope_key(session_id)}.ndjson"
    )


def _append_runtime_trace(
    storage_root: Path,
    *,
    installation_id: str,
    session_id: str,
    invocation_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    path = runtime_trace_path(
        storage_root,
        installation_id=installation_id,
        session_id=session_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "installation_id": installation_id,
        "session_id": session_id,
        "invocation_id": invocation_id,
        "event_type": event_type,
        "payload": payload or {},
    }
    encoded = (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def is_workspace_business_turn(
    query: str | None,
    *,
    mission_info: dict[str, Any] | None,
) -> bool:
    """Closed classification shared by standard Runner entry paths."""
    if mission_info is not None:
        return False
    return not bool(query and query.lstrip().startswith("/"))


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, Msg):
        return message.to_dict()
    if hasattr(message, "to_dict"):
        return dict(message.to_dict())
    if isinstance(message, dict):
        return dict(message)
    raise WorkspaceOrchestrationError("orchestration_error")


async def run_workspace_orchestration_turn(
    *,
    agent: Any,
    original_messages: list[Any],
    request: Any,
    agent_id: str,
    workspace_root: Path,
    state_storage_root: Path,
    config: OrchestrationConfig,
    authorization: AuthorizedWorkspaceRelease,
    business_call: Callable[[str, dict[str, Any]], Any] | None = None,
    timeout_seconds: float = 30.0,
) -> WorkspaceTurnResult:
    invocation_id = uuid.uuid4().hex
    transaction = WorkspaceStateTransaction.begin(
        state_storage_root,
        installation_id=authorization.installation_id,
        session_id=str(request.session_id),
        invocation_id=invocation_id,
    )
    serialized_messages = [_message_dict(message) for message in original_messages]
    trusted_context = {
        "session_id": str(request.session_id),
        "user_id": str(request.user_id),
        "channel": str(request.channel),
        "agent_id": agent_id,
        "normalized_input": {"messages": serialized_messages},
        "history": serialized_messages,
    }
    turn_request = WorkspaceTurnRequest(
        invocation_id=invocation_id,
        agent_id=agent_id,
        release_id=authorization.release_id,
        release_digest=authorization.release_digest,
        installation_id=authorization.installation_id,
        session_id=trusted_context["session_id"],
        user_id=trusted_context["user_id"],
        channel=trusted_context["channel"],
        normalized_input={"messages": serialized_messages},
        history=serialized_messages,
        safe_metadata={},
        diagnostics_authorized=False,
        granted_capabilities=dict(authorization.granted_capabilities),
        state_root=transaction.state_root,
        transaction_root=transaction.transaction_root,
    )
    _append_runtime_trace(
        state_storage_root,
        installation_id=authorization.installation_id,
        session_id=turn_request.session_id,
        invocation_id=invocation_id,
        event_type="orchestration.started",
    )

    async def execute_agent(arguments: dict[str, Any]) -> dict[str, Any]:
        raw_messages = arguments.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise WorkspaceOrchestrationError("orchestration_error")
        try:
            messages = [
                item if isinstance(item, Msg) else Msg.from_dict(item)
                for item in raw_messages
            ]
        except Exception as exc:
            raise WorkspaceOrchestrationError("orchestration_error") from exc
        candidate = await agent(messages)
        serialized = _message_dict(candidate)
        text = (
            candidate.get_text_content()
            if hasattr(candidate, "get_text_content")
            else str(serialized.get("content", ""))
        )
        return {"message": serialized, "text": text}

    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace_root,
        config=config,
        signed_files=authorization.signed_workspace_files,
        execute_agent=execute_agent,
        session_context=lambda: trusted_context,
        business_call=business_call,
        trace_sink=lambda trace: _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=invocation_id,
            event_type="runtime.trace",
            payload=trace,
        ),
        timeout_seconds=timeout_seconds,
    )
    result = await orchestrator.invoke(turn_request, transaction)
    _append_runtime_trace(
        state_storage_root,
        installation_id=authorization.installation_id,
        session_id=turn_request.session_id,
        invocation_id=invocation_id,
        event_type=(
            "orchestration.completed"
            if result.error_code is None
            else "orchestration.failed"
        ),
        payload={"error_code": result.error_code} if result.error_code else {},
    )
    return result


class WorkspaceStateTransaction:
    """Copy-on-write state directory promoted only after valid completion."""

    def __init__(
        self,
        *,
        invocation_id: str,
        state_root: Path,
        transaction_root: Path,
        base_digest: str | None,
    ) -> None:
        self.invocation_id = invocation_id
        self.state_root = state_root
        self.transaction_root = transaction_root
        self.base_digest = base_digest
        self._finished = False

    @classmethod
    def begin(
        cls,
        storage_root: Path,
        *,
        installation_id: str,
        session_id: str,
        invocation_id: str,
    ) -> "WorkspaceStateTransaction":
        storage = Path(storage_root)
        storage.mkdir(parents=True, exist_ok=True)
        storage = storage.resolve(strict=True)
        state_root = (
            storage
            / "state"
            / _scope_key(installation_id)
            / _scope_key(session_id)
        )
        transaction_root = (
            storage
            / "transactions"
            / _scope_key(invocation_id)
        )
        transaction_root.parent.mkdir(parents=True, exist_ok=True)
        if transaction_root.exists():
            raise WorkspaceOrchestrationError("orchestration_error")
        if state_root.exists():
            if state_root.is_symlink() or not state_root.is_dir():
                raise WorkspaceOrchestrationError("orchestration_error")
            shutil.copytree(state_root, transaction_root, symlinks=False)
            base_digest = _directory_digest(state_root)
        else:
            transaction_root.mkdir(parents=True)
            base_digest = None
        return cls(
            invocation_id=invocation_id,
            state_root=state_root,
            transaction_root=transaction_root,
            base_digest=base_digest,
        )

    def commit(self) -> None:
        if self._finished or not self.transaction_root.is_dir():
            raise WorkspaceOrchestrationError("invalid_completion")
        self.state_root.parent.mkdir(parents=True, exist_ok=True)
        backup = self.state_root.with_name(
            f"{self.state_root.name}.backup-{_scope_key(self.invocation_id)[:12]}",
        )
        with _exclusive_state_lock(self.state_root.with_suffix(".lock")):
            current_digest = (
                _directory_digest(self.state_root)
                if self.state_root.exists()
                else None
            )
            if current_digest != self.base_digest:
                raise WorkspaceOrchestrationError("orchestration_error")
            if backup.exists():
                shutil.rmtree(backup)
            moved_old = False
            try:
                if self.state_root.exists():
                    os.replace(self.state_root, backup)
                    moved_old = True
                os.replace(self.transaction_root, self.state_root)
            except Exception:
                if moved_old and backup.exists() and not self.state_root.exists():
                    os.replace(backup, self.state_root)
                raise
            else:
                if backup.exists():
                    shutil.rmtree(backup)
                self._finished = True

    def discard(self) -> None:
        if self._finished:
            return
        shutil.rmtree(self.transaction_root, ignore_errors=True)
        self._finished = True


def _directory_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise WorkspaceOrchestrationError("orchestration_error")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix().encode("utf-8")
        content = candidate.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


@contextmanager
def _exclusive_state_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class WorkspaceRuntimeHost:
    def __init__(
        self,
        *,
        request: WorkspaceTurnRequest,
        execute_agent: Callable[[dict[str, Any]], Any],
        session_context: Callable[[], Any],
        business_call: Callable[[str, dict[str, Any]], Any] | None = None,
        trace_sink: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.request = request
        self._execute_agent = execute_agent
        self._session_context = session_context
        self._business_call = business_call
        self._trace_sink = trace_sink
        self.completion: WorkspaceTurnCompletion | None = None
        self.failure: WorkspaceTurnFailure | None = None

    async def call(self, capability: str, arguments: dict[str, Any]) -> Any:
        if self.completion is not None or self.failure is not None:
            raise WorkspaceOrchestrationError("invalid_completion")
        if self.request.granted_capabilities.get(capability) != "1":
            raise WorkspaceOrchestrationError("unauthorized_capability")
        if capability == "agent.execute":
            return await _maybe_await(self._execute_agent(arguments))
        if capability == "session.context":
            return await _maybe_await(self._session_context())
        if capability == "runtime.trace":
            if self._trace_sink is not None:
                await _maybe_await(self._trace_sink({
                    "invocation_id": self.request.invocation_id,
                    "agent_id": self.request.agent_id,
                    "session_id": self.request.session_id,
                    "payload": dict(arguments),
                }))
            return {"accepted": True}
        if capability == "runtime.complete":
            completion = WorkspaceTurnCompletion.model_validate(arguments)
            if completion.invocation_id != self.request.invocation_id:
                raise WorkspaceOrchestrationError("invalid_completion")
            self.completion = completion
            return {"accepted": True}
        if capability == "runtime.fail":
            failure = WorkspaceTurnFailure.model_validate(arguments)
            if failure.invocation_id != self.request.invocation_id:
                raise WorkspaceOrchestrationError("invalid_completion")
            self.failure = failure
            return {"accepted": True}
        if self._business_call is None:
            raise WorkspaceOrchestrationError("unauthorized_capability")
        return await _maybe_await(self._business_call(capability, arguments))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class WorkspaceTurnOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: Path,
        config: OrchestrationConfig,
        signed_files: frozenset[str],
        execute_agent: Callable[[dict[str, Any]], Any],
        session_context: Callable[[], Any],
        business_call: Callable[[str, dict[str, Any]], Any] | None = None,
        trace_sink: Callable[[dict[str, Any]], Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.config = config
        self.signed_files = signed_files
        self.execute_agent = execute_agent
        self.session_context = session_context
        self.business_call = business_call
        self.trace_sink = trace_sink
        self.timeout_seconds = timeout_seconds

    async def invoke(
        self,
        request: WorkspaceTurnRequest,
        transaction: WorkspaceStateTransaction,
    ) -> WorkspaceTurnResult:
        host = WorkspaceRuntimeHost(
            request=request,
            execute_agent=self.execute_agent,
            session_context=self.session_context,
            business_call=self.business_call,
            trace_sink=self.trace_sink,
        )
        try:
            runtime = self._load_runtime()
            result = runtime.handle(request, host)
            if not inspect.isawaitable(result):
                raise WorkspaceOrchestrationError("orchestration_error")
            await asyncio.wait_for(result, timeout=self.timeout_seconds)
            if host.failure is not None:
                transaction.discard()
                return WorkspaceTurnResult(error_code=host.failure.error_code)
            if host.completion is None:
                raise WorkspaceOrchestrationError("invalid_completion")
            _validate_render_bound_message(host.completion.message)
            transaction.commit()
            return WorkspaceTurnResult(
                message=host.completion.message,
                diagnostics=host.completion.diagnostics,
            )
        except asyncio.TimeoutError:
            transaction.discard()
            return WorkspaceTurnResult(error_code="orchestration_timeout")
        except WorkspaceOrchestrationError as exc:
            transaction.discard()
            return WorkspaceTurnResult(error_code=exc.error_code)
        except Exception:
            transaction.discard()
            return WorkspaceTurnResult(error_code="orchestration_error")

    def _load_runtime(self) -> Any:
        module_name, factory_name = self.config.entrypoint.split(":", 1)
        normalized = PurePosixPath(module_name).as_posix()
        if normalized not in self.signed_files:
            raise WorkspaceOrchestrationError("orchestration_error")
        root = self.workspace_root.resolve(strict=True)
        candidate = self.workspace_root / normalized
        if candidate.is_symlink():
            raise WorkspaceOrchestrationError("orchestration_error")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise WorkspaceOrchestrationError("orchestration_error")
        spec = importlib.util.spec_from_file_location(
            f"dclaw_workspace_runtime_{uuid.uuid4().hex}",
            resolved,
        )
        if spec is None or spec.loader is None:
            raise WorkspaceOrchestrationError("orchestration_error")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        factory = getattr(module, factory_name, None)
        if not callable(factory):
            raise WorkspaceOrchestrationError("orchestration_error")
        runtime = factory()
        if runtime is None or not callable(getattr(runtime, "handle", None)):
            raise WorkspaceOrchestrationError("orchestration_error")
        return runtime
