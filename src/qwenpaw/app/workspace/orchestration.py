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
import sys
import time
import types
import uuid
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

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
_CANDIDATE_AGENT_LOCKS: dict[int, asyncio.Lock] = {}
_INTERNAL_CANDIDATE_MAX_TOKENS = 4096
_JSON_INTERNAL_CANDIDATE_MAX_TOKENS = 8192
_DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS = 180.0
_MIN_ORCHESTRATION_TIMEOUT_SECONDS = 30.0
_MAX_ORCHESTRATION_TIMEOUT_SECONDS = 900.0
_MAX_AUTOMATIC_CONTINUATION_PASSES = 8


def workspace_orchestration_timeout_seconds() -> float:
    """Return the bounded deadline for a complete Agent-owned business turn."""
    raw = os.environ.get("DCLAW_WORKSPACE_ORCHESTRATION_TIMEOUT_SECONDS", "")
    try:
        value = float(raw) if raw.strip() else _DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        value = _DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS
    return min(
        max(value, _MIN_ORCHESTRATION_TIMEOUT_SECONDS),
        _MAX_ORCHESTRATION_TIMEOUT_SECONDS,
    )


def workspace_raw_model_trace_enabled() -> bool:
    """Enable full local agent.execute tracing only through an explicit flag."""
    return os.environ.get("DCLAW_WORKSPACE_MODEL_TRACE_RAW", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


class WorkspaceOrchestrationError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class WorkspaceTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    error_code: str | None = None
    diagnostic_ref: str | None = Field(default=None, max_length=200)


@dataclass(frozen=True)
class AuthorizedWorkspaceRelease:
    installation_id: str
    release_id: str
    release_digest: str
    granted_capabilities: dict[str, str]
    signed_workspace_files: frozenset[str]
    signed_workspace_root: Path | None = None


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
    sealed_root = Path(release_root).parents[2]
    expected_workspace = (
        sealed_root
        / "runtime_workspaces"
        / record.agent_id
        / release.release_id
        / "agent"
    ).resolve(strict=True)
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
        signed_workspace_root=(Path(release_root) / "agent").resolve(strict=True),
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
        content = message["reply"]
        display_text = (result.diagnostics or {}).get("display_text")
        if isinstance(display_text, str) and display_text:
            content = [
                {"type": "text", "text": message["reply"]},
                {"type": "text", "text": "\n\n---\n\n" + display_text},
            ]
        return Msg(name=agent_name, role="assistant", content=content)
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


def _candidate_execution_messages(messages: list[Msg]) -> list[Msg]:
    """Project runtime-owned instructions into a standard Agent user turn.

    Standard DClaw Agents own a fixed system prompt and do not treat incoming
    system-role messages as an override. ``agent.execute`` is internal-only,
    so the runtime instruction is appended as the final, explicit candidate
    generation request instead of being silently ignored.
    """
    instructions = [
        message.get_text_content()
        for message in messages
        if message.role == "system" and message.get_text_content().strip()
    ]
    projected = [message for message in messages if message.role != "system"]
    if instructions:
        projected.append(
            Msg(
                name="workspace_runtime",
                role="user",
                content=(
                    "以下是本轮内部候选生成指令。必须严格执行；只生成内部候选，"
                    "不要向客户解释这段指令。\n\n"
                    + "\n\n".join(instructions)
                    + "\n\n再次确认：必须严格遵守上述输出格式；只输出要求的内部候选，"
                    "不得输出面向客户的普通回答或任何前后解释。"
                ),
            )
        )
    return projected


async def _execute_internal_candidate(
    agent: Any, messages: list[Msg], *, media_delivery: dict[str, Any] | None = None,
    response_format: str | None = None,
) -> Any:
    """Execute with runtime instructions at system authority, then restore."""
    if response_format is not None and response_format != "json_object":
        raise WorkspaceOrchestrationError("orchestration_error")
    from .media_delivery import media_input_manifest, media_input_identities, build_media_delivery
    if media_delivery is not None:
        media_delivery.clear()
    manifest = media_input_manifest(messages) if media_delivery is not None else []
    identities = media_input_identities(messages) if manifest else []
    formatter = getattr(agent, "formatter", None)
    model = getattr(agent, "model", None)
    if formatter is not None and callable(getattr(formatter, "format", None)) and callable(model):
        prompt = await formatter.format(msgs=messages)
        generation_kwargs: dict[str, Any] = {
            "max_tokens": (
                _JSON_INTERNAL_CANDIDATE_MAX_TOKENS
                if response_format == "json_object"
                else _INTERNAL_CANDIDATE_MAX_TOKENS
            ),
        }
        if response_format == "json_object":
            generation_kwargs["response_format"] = {"type": "json_object"}
        model_key = str(getattr(model, "model_key", "")).lower()
        if model_key.startswith("volcengine-cn:") and "deepseek" in model_key:
            generation_kwargs["extra_body"] = {
                "thinking": {"type": "disabled"},
            }
        response = await model(
            prompt,
            tools=None,
            tool_choice="none",
            **generation_kwargs,
        )
        candidate = Msg(
            name=str(getattr(agent, "name", "assistant")),
            role="assistant",
            content=[],
        )
        if bool(getattr(model, "stream", False)):
            async for chunk in response:
                streamed = Msg(
                    name=str(getattr(agent, "name", "assistant")),
                    role="assistant",
                    content=chunk.content,
                )
                if streamed.get_text_content():
                    candidate.invocation_id = chunk.id
                    candidate.content = chunk.content
        else:
            candidate.invocation_id = response.id
            candidate.content = list(response.content)
        if media_delivery is not None and (candidate.get_text_content() or '').strip():
            media_delivery.update(build_media_delivery(manifest, prompt, candidate.invocation_id,
                                                       input_identities=identities))
        return candidate

    if response_format is not None:
        raise WorkspaceOrchestrationError("orchestration_error")
    instructions = [
        message.get_text_content()
        for message in messages
        if message.role == "system" and message.get_text_content().strip()
    ]
    projected = _candidate_execution_messages(messages)
    if not instructions or not hasattr(agent, "_sys_prompt"):
        return await agent(projected)
    lock = _CANDIDATE_AGENT_LOCKS.setdefault(id(agent), asyncio.Lock())
    async with lock:
        original_prompt = agent._sys_prompt
        original_prompt_builder = getattr(agent, "_build_sys_prompt", None)
        runtime_prompt = (
            f"{original_prompt}\n\n"
            "===== TRUSTED WORKSPACE RUNTIME INSTRUCTION =====\n"
            + "\n\n".join(instructions)
            + "\n===== END TRUSTED WORKSPACE RUNTIME INSTRUCTION ====="
        )
        system_message = None
        original_memory_content = None
        memory = getattr(agent, "memory", None)
        for item in getattr(memory, "content", ()):
            message = item[0] if isinstance(item, tuple) else item
            if getattr(message, "role", None) == "system":
                system_message = message
                original_memory_content = message.content
                break
        agent._sys_prompt = runtime_prompt
        if callable(original_prompt_builder):
            agent._build_sys_prompt = lambda: runtime_prompt
        if system_message is not None:
            system_message.content = runtime_prompt
        try:
            return await agent(projected)
        finally:
            agent._sys_prompt = original_prompt
            if callable(original_prompt_builder):
                agent._build_sys_prompt = original_prompt_builder
            if system_message is not None:
                system_message.content = original_memory_content


def _agent_execute_response_format(arguments: dict[str, Any]) -> str | None:
    """Validate the optional host capability argument without truthy coercion."""
    if not isinstance(arguments, dict):
        raise WorkspaceOrchestrationError("orchestration_error")
    if "response_format" not in arguments:
        return None
    if arguments["response_format"] != "json_object":
        raise WorkspaceOrchestrationError("orchestration_error")
    return "json_object"


def _agent_execute_mode(arguments: dict[str, Any]) -> str:
    """Select the host execution path without truthy coercion."""
    if not isinstance(arguments, dict):
        raise WorkspaceOrchestrationError("orchestration_error")
    if "execution_mode" not in arguments:
        return "candidate"
    if arguments["execution_mode"] != "agent_loop":
        raise WorkspaceOrchestrationError("orchestration_error")
    return "agent_loop"


async def run_workspace_orchestration_turn(
    *,
    agent: Any,
    original_messages: list[Any],
    conversation_history: list[Any] | None = None,
    request: Any,
    agent_id: str,
    workspace_root: Path,
    state_storage_root: Path,
    config: OrchestrationConfig,
    authorization: AuthorizedWorkspaceRelease,
    business_call: Callable[[str, dict[str, Any]], Any] | None = None,
    safe_metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> WorkspaceTurnResult:
    invocation_id = uuid.uuid4().hex
    transaction = WorkspaceStateTransaction.begin(
        state_storage_root,
        installation_id=authorization.installation_id,
        session_id=str(request.session_id),
        invocation_id=invocation_id,
    )
    serialized_messages = [_message_dict(message) for message in original_messages]
    serialized_history = [
        _message_dict(message) for message in (conversation_history or [])
    ]
    trusted_context = {
        "session_id": str(request.session_id),
        "user_id": str(request.user_id),
        "channel": str(request.channel),
        "agent_id": agent_id,
        "normalized_input": {"messages": serialized_messages},
        "history": serialized_history,
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
        history=serialized_history,
        safe_metadata=dict(safe_metadata or {}),
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
    agent_execute_call_number = 0

    async def execute_agent(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal agent_execute_call_number
        response_format = _agent_execute_response_format(arguments)
        execution_mode = _agent_execute_mode(arguments)
        if execution_mode == "agent_loop" and response_format is not None:
            raise WorkspaceOrchestrationError("orchestration_error")
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
        agent_execute_call_number += 1
        call_number = agent_execute_call_number
        call_id = uuid.uuid4().hex
        started_at = time.perf_counter()
        trace_raw = workspace_raw_model_trace_enabled()
        if trace_raw:
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="agent.execute.started",
                payload={
                    "call_id": call_id,
                    "call_number": call_number,
                    "model_key": str(
                        getattr(getattr(agent, "model", None), "model_key", "")
                    ),
                    "execution_mode": execution_mode,
                    "response_format": response_format,
                    "messages": [_message_dict(message) for message in messages],
                },
            )
        media_delivery: dict[str, Any] = {}
        try:
            if execution_mode == "agent_loop":
                candidate = await agent(messages)
            else:
                candidate = await _execute_internal_candidate(
                    agent, messages, media_delivery=media_delivery,
                    response_format=response_format,
                )
        except Exception as exc:
            if trace_raw:
                _append_runtime_trace(
                    state_storage_root,
                    installation_id=authorization.installation_id,
                    session_id=turn_request.session_id,
                    invocation_id=invocation_id,
                    event_type="agent.execute.failed",
                    payload={
                        "call_id": call_id,
                        "call_number": call_number,
                        "duration_ms": max(
                            0, round((time.perf_counter() - started_at) * 1000)
                        ),
                        "exception_type": type(exc).__name__,
                        "error": str(exc)[:2000],
                    },
                )
            logger.exception("Internal candidate execution failed")
            raise
        serialized = _message_dict(candidate)
        text = (
            candidate.get_text_content()
            if hasattr(candidate, "get_text_content")
            else str(serialized.get("content", ""))
        )
        result = {"message": serialized, "text": text}
        if media_delivery:
            result["media_delivery"] = media_delivery
        if trace_raw:
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="agent.execute.completed",
                payload={
                    "call_id": call_id,
                    "call_number": call_number,
                    "duration_ms": max(
                        0, round((time.perf_counter() - started_at) * 1000)
                    ),
                    "response_id": str(
                        getattr(candidate, "invocation_id", "") or serialized.get("id", "")
                    ),
                    "has_text": bool(text.strip()),
                    "text_length": len(text),
                    "text": text,
                    "message": serialized,
                },
            )
        return result

    actual_timeout = (workspace_orchestration_timeout_seconds()
                      if timeout_seconds is None else timeout_seconds)

    def build_orchestrator(active_invocation_id: str) -> "WorkspaceTurnOrchestrator":
        return WorkspaceTurnOrchestrator(
            workspace_root=workspace_root, config=config,
            signed_files=authorization.signed_workspace_files,
            execute_agent=execute_agent, session_context=lambda: trusted_context,
            business_call=business_call,
            trace_sink=lambda trace: _append_runtime_trace(
                state_storage_root, installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=active_invocation_id, event_type="runtime.trace", payload=trace,
            ), timeout_seconds=actual_timeout,
        )

    orchestrator = build_orchestrator(invocation_id)
    try:
        result = await orchestrator.invoke(turn_request, transaction)
    except asyncio.CancelledError:
        _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=invocation_id,
            event_type="orchestration.cancelled",
            payload={"error_code": "cancelled"},
        )
        raise
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
        payload=(
            {
                "error_code": result.error_code,
                "diagnostic_ref": result.diagnostic_ref,
            }
            if result.error_code
            else {}
        ),
    )
    last_committed_result = result if result.error_code is None else None
    continuation_pass = 0
    while (
        result.error_code is None
        and (result.diagnostics or {}).get("continuation_reason") == "turn_budget_exhausted"
        and continuation_pass < _MAX_AUTOMATIC_CONTINUATION_PASSES
    ):
        continuation_pass += 1
        continuation_invocation_id = uuid.uuid4().hex
        continuation_transaction = WorkspaceStateTransaction.begin(
            state_storage_root, installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=continuation_invocation_id,
        )
        continuation_request = turn_request.model_copy(update={
            "invocation_id": continuation_invocation_id,
            "state_root": continuation_transaction.state_root,
            "transaction_root": continuation_transaction.transaction_root,
            # This is a host continuation signal, not a fabricated customer
            # command. Unconsumed input is restored from pending_input.
            "normalized_input": {"messages": [{
                "name": "customer", "role": "user", "content": "",
            }]},
            "safe_metadata": {
                key: deepcopy(value) for key, value in turn_request.safe_metadata.items()
                if key != "conversationReset"
            },
        })
        continuation_request._runtime_continuation = True
        _append_runtime_trace(
            state_storage_root, installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=continuation_invocation_id,
            event_type="orchestration.continuation.started",
            payload={"pass": continuation_pass},
        )
        try:
            continued = await build_orchestrator(continuation_invocation_id).invoke(
                continuation_request, continuation_transaction,
            )
        except asyncio.CancelledError:
            _append_runtime_trace(
                state_storage_root, installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=continuation_invocation_id,
                event_type="orchestration.cancelled", payload={"error_code": "cancelled"},
            )
            raise
        _append_runtime_trace(
            state_storage_root, installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=continuation_invocation_id,
            event_type=("orchestration.continuation.completed"
                        if continued.error_code is None else "orchestration.continuation.failed"),
            payload=({"pass": continuation_pass} if continued.error_code is None else {
                "pass": continuation_pass, "error_code": continued.error_code,
                "diagnostic_ref": continued.diagnostic_ref,
            }),
        )
        if continued.error_code is not None:
            # Earlier passes are already committed. Never replace their safe
            # completion with a later transient failure.
            result = last_committed_result or continued
            break
        result = continued
        last_committed_result = continued
    if ((result.diagnostics or {}).get("continuation_reason") == "turn_budget_exhausted"
            and continuation_pass >= _MAX_AUTOMATIC_CONTINUATION_PASSES):
        _append_runtime_trace(
            state_storage_root, installation_id=authorization.installation_id,
            session_id=turn_request.session_id, invocation_id=turn_request.invocation_id,
            event_type="orchestration.continuation.limit_reached",
            payload={"max_passes": _MAX_AUTOMATIC_CONTINUATION_PASSES},
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
        timeout_seconds: float | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.config = config
        self.signed_files = signed_files
        self.execute_agent = execute_agent
        self.session_context = session_context
        self.business_call = business_call
        self.trace_sink = trace_sink
        self.timeout_seconds = (
            workspace_orchestration_timeout_seconds()
            if timeout_seconds is None
            else timeout_seconds
        )
        self._runtime_module_prefix: str | None = None

    async def invoke(
        self,
        request: WorkspaceTurnRequest,
        transaction: WorkspaceStateTransaction,
    ) -> WorkspaceTurnResult:
        loop = asyncio.get_running_loop()
        reserve = min(2.0, max(0.02, self.timeout_seconds * 0.1))
        # Private Pydantic attributes are host-owned and are never accepted in
        # WorkspaceTurnRequest input or exposed through model_dump/json schema.
        request._runtime_deadline_monotonic = loop.time() + self.timeout_seconds
        request._runtime_deadline_reserve_seconds = reserve
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
                logger.error(
                    "Workspace runtime reported failure (%s)",
                    host.failure.diagnostic_ref or host.failure.error_code,
                )
                transaction.discard()
                return WorkspaceTurnResult(
                    error_code=host.failure.error_code,
                    diagnostic_ref=host.failure.diagnostic_ref,
                )
            if host.completion is None:
                raise WorkspaceOrchestrationError("invalid_completion")
            _validate_render_bound_message(host.completion.message)
            transaction.commit()
            return WorkspaceTurnResult(
                message=host.completion.message,
                diagnostics=host.completion.diagnostics,
            )
        except asyncio.CancelledError:
            transaction.discard()
            raise
        except asyncio.TimeoutError:
            transaction.discard()
            return WorkspaceTurnResult(
                error_code="orchestration_timeout",
                diagnostic_ref="asyncio.TimeoutError",
            )
        except WorkspaceOrchestrationError as exc:
            transaction.discard()
            return WorkspaceTurnResult(
                error_code=exc.error_code,
                diagnostic_ref=f"WorkspaceOrchestrationError:{exc.error_code}",
            )
        except Exception as exc:
            transaction.discard()
            return WorkspaceTurnResult(
                error_code="orchestration_error",
                diagnostic_ref=type(exc).__name__,
            )
        finally:
            self._cleanup_runtime_modules()

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
        prefix = f"dclaw_workspace_{uuid.uuid4().hex}"
        package = types.ModuleType(prefix)
        package.__path__ = [str(root)]
        package.__package__ = prefix
        sys.modules[prefix] = package
        module_name = f"{prefix}.runtime"
        spec = importlib.util.spec_from_file_location(module_name, resolved)
        if spec is None or spec.loader is None:
            sys.modules.pop(prefix, None)
            raise WorkspaceOrchestrationError("orchestration_error")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self._runtime_module_prefix = prefix
        try:
            spec.loader.exec_module(module)
        except BaseException:
            self._cleanup_runtime_modules()
            raise
        factory = getattr(module, factory_name, None)
        if not callable(factory):
            raise WorkspaceOrchestrationError("orchestration_error")
        runtime = factory()
        if runtime is None or not callable(getattr(runtime, "handle", None)):
            raise WorkspaceOrchestrationError("orchestration_error")
        return runtime

    def _cleanup_runtime_modules(self) -> None:
        prefix = self._runtime_module_prefix
        if prefix is None:
            return
        for name in tuple(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
        self._runtime_module_prefix = None
