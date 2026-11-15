"""Generic, fail-closed execution of Agent-owned workspace runtimes."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import re
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
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.app.sealed_agents.models import SealedAgentRecord
from qwenpaw.app.sealed_agents.registry import get_sealed_agent_registry
from qwenpaw.app.sealed_agents.package import (
    SealedPackageError,
)
from .release_integrity import inspect_signed_release
from .grants import SuperExpertGrantRepository
from qwenpaw.constant import WORKING_DIR
from agentscope.message import Msg

from .orchestration_contract import (
    WorkspaceTurnCompletion,
    WorkspaceTurnFailure,
    WorkspaceTurnRequest,
)
from . import aigc_tools as _aigc_tools
from . import composition as _composition
from . import empty_reply as _empty_reply
from . import failure_diagnostics as _failure_diagnostics
from . import interaction_contract as _interaction_contract
from . import interaction_tools as _interaction_tools
from .interaction_receipts import card_receipt
from . import media_delivery as _media_delivery
from . import media_review_context as _media_review_context
from . import public_stream as _public_stream
from .public_runtime import PublicRuntimeError, invoke_public_runtime

logger = logging.getLogger(__name__)
_CANDIDATE_AGENT_LOCKS: dict[int, asyncio.Lock] = {}
_INTERNAL_CANDIDATE_MAX_TOKENS = 4096
_JSON_INTERNAL_CANDIDATE_MAX_TOKENS = 8192
_DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS = 180.0
_MIN_ORCHESTRATION_TIMEOUT_SECONDS = 30.0
_MAX_ORCHESTRATION_TIMEOUT_SECONDS = 900.0
_MAX_AUTOMATIC_CONTINUATION_PASSES = 8
_PLATFORM_REVIEW_PREFIX = "当前绑定的 DClaw AIGC 素材已由客户明确提交。任务ID："
_AIGC_REVIEW_CONTINUATION_INSTRUCTION = (
    "The current host-submitted AIGC review has been accepted. Continue the "
    "user's still-pending request from the existing conversation using only "
    "the governed AIGC workflow tools now available. Do not repeat the review "
    "and do not ask the user to send another confirmation or continue message."
)
_INTERACTION_DELIVERY_PREFIX = re.compile(
    r"^\s*"
    r"(?:(?:好(?:了|的)?|可以|行)[，,。.!！；;：:]?\s*)?"
    r"(?:(?:这张|这个|该|交互)?卡片)"
    r"(?:已经|已)?"
    r"(?:"
    r"发(?:送)?(?:给你|过去|出去|出)?"
    r"|发送成功"
    r"|创建(?:好|完成|成功)"
    r")"
    r"了?(?:\s*[，,。.!！；;：:]\s*|\s*$)",
)


def _drop_prior_platform_review_attempts(memory: Any) -> int:
    """Remove stale platform-generated review turns from Agent context."""
    content = getattr(memory, "content", None)
    if not isinstance(content, list):
        return 0
    kept = []
    dropping = False
    removed = 0
    for item in content:
        message = item[0] if isinstance(item, (tuple, list)) and item else item
        role = str(getattr(message, "role", "") or "")
        text = ""
        get_text = getattr(message, "get_text_content", None)
        if callable(get_text):
            text = str(get_text() or "")
        is_review_start = role == "user" and text.startswith(
            _PLATFORM_REVIEW_PREFIX,
        )
        if is_review_start:
            dropping = True
            removed += 1
            continue
        if dropping and role == "user":
            dropping = False
        if dropping:
            removed += 1
            continue
        kept.append(item)
    if removed:
        memory.content = kept
    return removed


def workspace_orchestration_timeout_seconds() -> float:
    """Return the bounded deadline for a complete Agent-owned business turn."""
    raw = os.environ.get("DCLAW_WORKSPACE_ORCHESTRATION_TIMEOUT_SECONDS", "")
    try:
        value = (
            float(raw)
            if raw.strip()
            else _DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        value = _DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS
    return min(
        max(value, _MIN_ORCHESTRATION_TIMEOUT_SECONDS),
        _MAX_ORCHESTRATION_TIMEOUT_SECONDS,
    )


def workspace_raw_model_trace_enabled() -> bool:
    """Enable full local agent.execute tracing only through an explicit flag."""
    return os.environ.get(
        "DCLAW_WORKSPACE_MODEL_TRACE_RAW",
        "",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class WorkspaceOrchestrationError(RuntimeError):
    def __init__(self, error_code: str, diagnostic_ref: str | None = None) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.diagnostic_ref = diagnostic_ref


class AigcLocalizationHostError(WorkspaceOrchestrationError):
    def __init__(self, *, stage: str, code: str, responsibility: str,
                 recovery_action: str, field_path: str = "not_recorded",
                 constraint: str = "not_recorded") -> None:
        super().__init__("orchestration_error")
        self.stage = stage
        self.diagnostic_code = code
        self.responsibility = responsibility
        self.recovery_action = recovery_action
        self.field_path = field_path
        self.constraint = constraint


def _log_aigc_localization_internal_error(
    exc: Exception, *, stage: str, invocation_id: str,
) -> None:
    frame = exc.__traceback__
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    source = (
        f"{Path(frame.tb_frame.f_code.co_filename).name}:{frame.tb_lineno}"
        if frame is not None else "not_recorded"
    )
    logger.error(
        "AIGC localization Host error invocation=%s stage=%s type=%s source=%s",
        invocation_id, stage, type(exc).__name__, source,
    )


class WorkspaceTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    verified_interaction_ids: tuple[str, ...] = ()
    error_code: str | None = None
    diagnostic_ref: str | None = Field(default=None, max_length=200)
    invocation_id: str | None = None


@dataclass(frozen=True)
class AuthorizedWorkspaceRelease:
    installation_id: str
    release_id: str
    release_digest: str
    granted_capabilities: dict[str, str]
    signed_workspace_files: frozenset[str]
    signed_workspace_root: Path | None = None
    package_type: str = "super_expert"


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
        or release.package_type not in {"super_expert", "super_expert_public"}
        or release.orchestration_capability_id
        != "workspace.turn.orchestrate/1"
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
        actual_digest, signed_files = inspect_signed_release(
            release_root, release.content_digest,
        )
    except (OSError, SealedPackageError) as exc:
        raise WorkspaceOrchestrationError("orchestration_error") from exc
    if actual_digest != release.content_digest:
        raise WorkspaceOrchestrationError(
            "orchestration_error", "release_digest_mismatch",
        )
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
        signed_workspace_root=(Path(release_root) / "agent").resolve(
            strict=True,
        ),
        package_type=release.package_type,
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
        first = (result.diagnostics or {}).get("first_failure") or {}
        phase = _failure_diagnostics._token(first.get("phase"))
        category = _failure_diagnostics._token(first.get("category"))
        if phase == "model_validation":
            label = "专家输出格式校验失败"
            action = "请联系专家开发者修复输出格式后重试"
        elif phase == "agent_execute":
            label = "模型调用失败"
            action = "请检查模型服务与专家配置后重试"
        elif phase in {"turn_context", "platform_preflight"}:
            label = "专家运行环境检查失败"
            action = "请联系平台维护人员核查"
        else:
            label = "专家运行失败"
            action = "请稍后重试；若再次发生，请联系平台维护人员核查"
        reference = result.invocation_id or "未生成"
        return Msg(
            name=agent_name,
            role="assistant",
            content=(
                f"本轮处理未能安全完成：{label}。{action}。"
                f"关联 ID：{reference}"
            ),
            metadata={
                "dclaw_failure": {
                    "invocation_id": result.invocation_id,
                    "error_code": _failure_diagnostics._token(result.error_code),
                    "phase": phase,
                    "category": category,
                    "attempt": first.get("attempt") if type(first.get("attempt")) is int else None,
                },
            },
        )
    message = result.message
    verified_interaction_ids = tuple(
        interaction_id.strip()
        for interaction_id in result.verified_interaction_ids
        if isinstance(interaction_id, str) and interaction_id.strip()
    )
    verified_interaction_id = (
        verified_interaction_ids[-1] if verified_interaction_ids else None
    )

    def interaction_metadata() -> dict[str, Any] | None:
        if verified_interaction_id is None:
            return None
        metadata: dict[str, Any] = {
            "super_expert_interaction_id": verified_interaction_id,
        }
        if len(verified_interaction_ids) > 1:
            metadata["super_expert_interaction_ids"] = list(
                verified_interaction_ids,
            )
        return metadata

    if {"name", "role", "content"}.issubset(message):
        try:
            rendered = Msg.from_dict(message)
        except Exception as exc:
            raise WorkspaceOrchestrationError("invalid_completion") from exc
        if verified_interaction_id is not None:
            rendered.content = _sanitize_interaction_delivery_content(
                rendered.content,
            )
            rendered.metadata = {
                **(
                    rendered.metadata
                    if isinstance(rendered.metadata, dict)
                    else {}
                ),
                **(interaction_metadata() or {}),
            }
        return rendered
    if isinstance(message.get("reply"), str):
        content = message["reply"]
        if verified_interaction_id is not None:
            content = _sanitize_interaction_delivery_text(content)
        display_text = (result.diagnostics or {}).get("display_text")
        if isinstance(display_text, str) and display_text:
            content = [
                {"type": "text", "text": content},
                {"type": "text", "text": "\n\n---\n\n" + display_text},
            ]
        return Msg(
            name=agent_name,
            role="assistant",
            content=content,
            metadata=interaction_metadata(),
        )
    raise WorkspaceOrchestrationError("invalid_completion")


def _sanitize_interaction_delivery_text(text: str) -> str:
    return _INTERACTION_DELIVERY_PREFIX.sub("", text, count=1)


def _sanitize_interaction_delivery_content(content: Any) -> Any:
    if isinstance(content, str):
        return _sanitize_interaction_delivery_text(content)
    if not isinstance(content, list):
        return content
    sanitized = []
    pending_prefix = True
    for block in content:
        if not isinstance(block, dict):
            sanitized.append(block)
            continue
        rendered = dict(block)
        if pending_prefix and rendered.get("type") == "text":
            text = rendered.get("text")
            if isinstance(text, str):
                cleaned = _sanitize_interaction_delivery_text(text)
                rendered["text"] = cleaned
                pending_prefix = not cleaned.strip()
        sanitized.append(rendered)
    return sanitized


def _validate_render_bound_message(message: dict[str, Any]) -> None:
    if {"name", "role", "content"}.issubset(message):
        if message["role"] != "assistant" or not isinstance(
            message["name"],
            str,
        ):
            raise WorkspaceOrchestrationError("invalid_completion")
        return
    if isinstance(message.get("reply"), str):
        return
    raise WorkspaceOrchestrationError("invalid_completion")


def _scope_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state_binding_path(storage_root: Path, installation_id: str, session_id: str) -> Path:
    return (
        Path(storage_root) / "migrations" / "bindings"
        / _scope_key(installation_id) / f"{_scope_key(session_id)}.json"
    )


def _validate_state_binding(
    binding_path: Path,
    transaction_root: Path,
    installation_id: str,
    session_id: str,
) -> None:
    if not binding_path.exists():
        return
    if binding_path.is_symlink():
        raise WorkspaceOrchestrationError("orchestration_error", "state_scope_conflict")
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        filename = binding["filename"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise WorkspaceOrchestrationError("orchestration_error", "state_scope_conflict") from exc
    if (
        binding.get("installation_id") != installation_id
        or binding.get("session_id") != session_id
        or not isinstance(filename, str)
        or Path(filename).name != filename
        or not filename.endswith(".json")
    ):
        raise WorkspaceOrchestrationError("orchestration_error", "state_scope_conflict")
    state_files = {
        item.name for item in transaction_root.iterdir() if item.suffix == ".json"
    }
    if (
        state_files != {filename}
        or (transaction_root / filename).is_symlink()
        or not (transaction_root / filename).is_file()
    ):
        raise WorkspaceOrchestrationError("orchestration_error", "state_scope_conflict")


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
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
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
            ),
        )
    return projected


async def _execute_internal_candidate(
    agent: Any,
    messages: list[Msg],
    *,
    media_delivery: dict[str, Any] | None = None,
    response_format: str | None = None,
) -> Any:
    """Execute with runtime instructions at system authority, then restore."""
    if response_format is not None and response_format != "json_object":
        raise WorkspaceOrchestrationError("orchestration_error")
    if media_delivery is not None:
        media_delivery.clear()
    manifest = (
        _media_delivery.media_input_manifest(messages)
        if media_delivery is not None
        else []
    )
    identities = (
        _media_delivery.media_input_identities(messages) if manifest else []
    )
    formatter = getattr(agent, "formatter", None)
    model = getattr(agent, "model", None)
    if (
        formatter is not None
        and callable(getattr(formatter, "format", None))
        and callable(model)
    ):
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
        if (
            media_delivery is not None
            and (candidate.get_text_content() or "").strip()
        ):
            media_delivery.update(
                _media_delivery.build_media_delivery(
                    manifest,
                    prompt,
                    candidate.invocation_id,
                    input_identities=identities,
                ),
            )
        return candidate

    if response_format is not None:
        raise WorkspaceOrchestrationError("orchestration_error")
    instructions = [
        message.get_text_content()
        for message in messages
        if message.role == "system" and message.get_text_content().strip()
    ]
    projected = _candidate_execution_messages(messages)
    return await _execute_with_runtime_system_instruction(
        agent,
        "\n\n".join(instructions) if instructions else None,
        lambda: agent(projected),
    )


async def _execute_with_runtime_system_instruction(
    agent: Any,
    instruction: str | None,
    invoke: Callable[[], Awaitable[Any]],
    *,
    required: bool = False,
) -> Any:
    """Temporarily add trusted runtime policy without polluting chat history."""
    if instruction is None:
        return await invoke()
    if not hasattr(agent, "_sys_prompt"):
        if required:
            raise WorkspaceOrchestrationError("orchestration_error")
        return await invoke()
    lock = _CANDIDATE_AGENT_LOCKS.setdefault(id(agent), asyncio.Lock())
    async with lock:
        original_prompt = agent._sys_prompt
        original_prompt_builder = getattr(agent, "_build_sys_prompt", None)
        runtime_prompt = (
            f"{original_prompt}\n\n"
            "===== TRUSTED WORKSPACE RUNTIME INSTRUCTION =====\n"
            + instruction
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
            return await invoke()
        finally:
            agent._sys_prompt = original_prompt
            if callable(original_prompt_builder):
                agent._build_sys_prompt = original_prompt_builder
            if system_message is not None:
                system_message.content = original_memory_content


@contextmanager
def _require_active_interaction_before_text(
    agent: Any,
    read_card: Callable[[str], dict[str, Any] | None] | None,
    *,
    enabled: bool,
):
    """Force tool use until the platform confirms an active interaction."""
    if not enabled:
        yield
        return
    if read_card is None or not callable(getattr(agent, "_reasoning", None)):
        raise WorkspaceOrchestrationError("orchestration_error")
    original_reasoning = agent._reasoning

    async def guarded_reasoning(tool_choice=None):
        if read_card("") is None:
            tool_choice = "required"
        return await original_reasoning(tool_choice=tool_choice)

    agent._reasoning = guarded_reasoning
    try:
        yield
    finally:
        agent._reasoning = original_reasoning


def _agent_execute_response_format(arguments: dict[str, Any]) -> str | None:
    """Validate the optional host capability argument without truthy coercion."""
    if not isinstance(arguments, dict):
        raise WorkspaceOrchestrationError("orchestration_error")
    if "response_format" not in arguments:
        return None
    if arguments["response_format"] != "json_object":
        raise WorkspaceOrchestrationError("orchestration_error")
    return "json_object"


def _agent_execute_instruction(arguments: dict[str, Any]) -> str | None:
    """Validate an optional trusted instruction for the standard Agent loop."""
    if not isinstance(arguments, dict):
        raise WorkspaceOrchestrationError("orchestration_error")
    if "instruction" not in arguments:
        return None
    instruction = arguments["instruction"]
    if not isinstance(instruction, str) or not instruction.strip():
        raise WorkspaceOrchestrationError("orchestration_error")
    return instruction.strip()


def _agent_execute_require_interaction(arguments: dict[str, Any]) -> bool:
    """Validate the optional active-interaction postcondition."""
    if not isinstance(arguments, dict):
        raise WorkspaceOrchestrationError("orchestration_error")
    value = arguments.get("require_interaction", False)
    if type(value) is not bool:
        raise WorkspaceOrchestrationError("orchestration_error")
    return value


def _agent_execute_mode(arguments: dict[str, Any]) -> str:
    """Select the host execution path without truthy coercion."""
    if not isinstance(arguments, dict):
        raise WorkspaceOrchestrationError("orchestration_error")
    if "execution_mode" not in arguments:
        return "candidate"
    if arguments["execution_mode"] != "agent_loop":
        raise WorkspaceOrchestrationError("orchestration_error")
    return "agent_loop"


def _safe_provider_error(exc: Exception) -> dict[str, Any]:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if not isinstance(body, dict):
        body = {}

    def field(name: str) -> str | None:
        value = getattr(exc, name, None) or body.get(name)
        return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", value) else None

    return {
        "status_code": status if type(status) is int and 400 <= status <= 599 else None,
        "provider_code": field("code"),
        "provider_param": field("param"),
    }


def _agent_execute_message(item: Any) -> Msg:
    if isinstance(item, Msg):
        return item
    if isinstance(item, dict) and "name" not in item and item.get("role") in {
        "system", "user", "assistant", "tool",
    }:
        item = {"name": item["role"], **item}
    return Msg.from_dict(item)


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
    read_aigc_task: Callable[[str], dict[str, Any] | None] | None = None,
    read_interaction_card: Callable[[str], dict[str, Any] | None]
    | None = None,
    interaction_receipts: list[dict[str, Any]] | None = None,
    on_public_message: Callable | None = None,
    safe_metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
    invocation_id: str | None = None,
) -> WorkspaceTurnResult:
    invocation_id = invocation_id or uuid.uuid4().hex
    transaction = WorkspaceStateTransaction.begin(
        state_storage_root,
        installation_id=authorization.installation_id,
        session_id=str(request.session_id),
        invocation_id=invocation_id,
    )
    serialized_messages = [
        _message_dict(message) for message in original_messages
    ]
    serialized_history = [
        _message_dict(message) for message in (conversation_history or [])
    ]
    try:
        trusted_context = await PluginRegistry().enrich_workspace_context(
            {
                "session_id": str(request.session_id),
                "user_id": str(request.user_id),
                "channel": str(request.channel),
                "agent_id": agent_id,
                "agent_name": str(getattr(agent, "name", "") or agent_id),
                "installation_id": authorization.installation_id,
                "release_id": authorization.release_id,
                "normalized_input": {"messages": serialized_messages},
                "history": serialized_history,
            },
            granted_capabilities=authorization.granted_capabilities,
            invocation_id=invocation_id,
        )
        trusted_context["interaction_receipts"] = list(interaction_receipts or [])
    except Exception as exc:
        logger.exception("Plugin workspace context enrichment failed")
        raise WorkspaceOrchestrationError("orchestration_error") from exc
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
    created_interaction_ids: list[str] = []
    safe_receipt_statuses = frozenset({
        "queued", "running", "succeeded", "failed", "cancelled",
        "rejected", "not_found", "unavailable", "pending", "completed",
        "accepted", "PENDING", "SUBMITTED", "ACCEPTED", "FAILED",
    })

    async def tracked_business_call(
        capability: str,
        arguments: dict[str, Any],
    ) -> Any:
        if business_call is None:
            raise WorkspaceOrchestrationError("unauthorized_capability")
        started_at = time.perf_counter()
        if capability.startswith("interaction.card."):
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="interaction.operation.started",
                payload={"capability": capability},
            )
        else:
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="host.operation.started",
                payload={
                    "capability": capability,
                    **({"implementation_revision": "localize-diagnostics-v2"}
                       if capability == "aigc.task.assets.localize/1" else {}),
                },
            )
        try:
            value = await _maybe_await(business_call(capability, arguments))
        except Exception as exc:
            if capability.startswith("interaction.card."):
                _append_runtime_trace(
                    state_storage_root,
                    installation_id=authorization.installation_id,
                    session_id=turn_request.session_id,
                    invocation_id=invocation_id,
                    event_type="interaction.operation.failed",
                    payload={
                        "capability": capability,
                        "category": type(exc).__name__,
                        **_failure_diagnostics.classify_interaction_failure(exc, capability),
                    },
                )
            else:
                code = getattr(exc, "error_code", None)
                aigc_failure = exc if isinstance(exc, AigcLocalizationHostError) else None
                if capability == "aigc.task.assets.localize/1" and aigc_failure is None:
                    _log_aigc_localization_internal_error(
                        exc, stage="host_operation", invocation_id=invocation_id,
                    )
                    aigc_failure = AigcLocalizationHostError(
                        stage="host_operation", code="HOST_INTERNAL_ERROR",
                        responsibility="platform",
                        recovery_action="contact_platform_with_invocation_id",
                    )
                _append_runtime_trace(
                    state_storage_root,
                    installation_id=authorization.installation_id,
                    session_id=turn_request.session_id,
                    invocation_id=invocation_id,
                    event_type="host.operation.failed",
                    payload={
                        "capability": capability,
                        "category": (
                            "host_internal" if aigc_failure and aigc_failure.responsibility == "platform"
                            else "host_rejected" if isinstance(exc, WorkspaceOrchestrationError)
                            else "host_exception"
                        ),
                        "error_code": (
                            aigc_failure.diagnostic_code if aigc_failure else
                            code if isinstance(code, str) and _failure_diagnostics._ERROR_CODE.fullmatch(code) else None
                        ),
                        **({
                            "host_stage": aigc_failure.stage,
                            "field_path": aigc_failure.field_path,
                            "constraint": aigc_failure.constraint,
                            "responsibility": aigc_failure.responsibility,
                            "recovery_action": aigc_failure.recovery_action,
                        } if aigc_failure else {}),
                        "duration_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
                    },
                )
            raise
        if capability.startswith("interaction.card."):
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="interaction.operation.completed",
                payload={"capability": capability},
            )
        else:
            receipt = value if isinstance(value, dict) else {}
            raw_status = receipt.get("status")
            receipt_status = raw_status if isinstance(raw_status, str) and raw_status in safe_receipt_statuses else None
            receipt_error = receipt.get("error_code")
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="host.operation.completed",
                payload={
                    "capability": capability,
                    "status": receipt_status,
                    "error_code": receipt_error if isinstance(receipt_error, str) and _failure_diagnostics._ERROR_CODE.fullmatch(receipt_error) else None,
                    "task_accepted": bool(receipt.get("contract") == "local.task.receipt/1" and isinstance(receipt.get("task_id"), str)),
                    "duration_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
                },
            )
        if capability == "interaction.card.create/1" and isinstance(
            value,
            dict,
        ):
            interaction = value.get("interaction")
            interaction_id = (
                interaction.get("interaction_id")
                if isinstance(interaction, dict)
                else None
            )
            status = (
                interaction.get("status")
                if isinstance(interaction, dict)
                else None
            )
            if (
                status == "PENDING"
                and isinstance(interaction_id, str)
                and interaction_id.strip()
                and interaction_id.strip() not in created_interaction_ids
            ):
                created_interaction_ids.append(interaction_id.strip())
        return value

    effective_business_call = (
        tracked_business_call if business_call is not None else None
    )

    def attach_created_interactions(
        turn_result: WorkspaceTurnResult,
    ) -> WorkspaceTurnResult:
        diagnostics = dict(turn_result.diagnostics or {})
        diagnostics.pop("interaction_id", None)
        diagnostics.pop("interaction_ids", None)
        updates: dict[str, Any] = {"diagnostics": diagnostics}
        if turn_result.error_code is None and created_interaction_ids:
            updates["verified_interaction_ids"] = tuple(
                created_interaction_ids,
            )
        return turn_result.model_copy(update=updates)

    async def execute_agent(
        arguments: dict[str, Any],
        active_safe_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal agent_execute_call_number
        response_format = _agent_execute_response_format(arguments)
        execution_mode = _agent_execute_mode(arguments)
        instruction = _agent_execute_instruction(arguments)
        if active_safe_metadata.get("aigcReviewContinuation") is True:
            instruction = "\n\n".join(
                filter(
                    None,
                    (
                        instruction,
                        _AIGC_REVIEW_CONTINUATION_INSTRUCTION,
                    ),
                ),
            )
        require_interaction = _agent_execute_require_interaction(arguments)
        if instruction is not None and execution_mode != "agent_loop":
            raise WorkspaceOrchestrationError("orchestration_error")
        if require_interaction and execution_mode != "agent_loop":
            raise WorkspaceOrchestrationError("orchestration_error")
        public_stream = arguments.get("public_stream", False)
        if type(public_stream) is not bool or (
            public_stream and execution_mode != "agent_loop"
        ):
            raise WorkspaceOrchestrationError("orchestration_error")
        if execution_mode == "agent_loop" and response_format is not None:
            raise WorkspaceOrchestrationError("orchestration_error")
        if type(arguments.get("recover_empty_reply", False)) is not bool:
            raise WorkspaceOrchestrationError("orchestration_error")
        raw_messages = arguments.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise WorkspaceOrchestrationError("orchestration_error")
        try:
            messages = [_agent_execute_message(item) for item in raw_messages]
        except Exception as exc:
            raise WorkspaceOrchestrationError("orchestration_error") from exc
        agent_execute_call_number += 1
        call_number = agent_execute_call_number
        call_id = uuid.uuid4().hex
        started_at = time.perf_counter()
        _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=invocation_id,
            event_type="agent.execute.safe_started",
            payload={
                "call_number": call_number,
                "execution_mode": execution_mode,
                "response_format": response_format,
            },
        )
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
                        getattr(
                            getattr(agent, "model", None),
                            "model_key",
                            "",
                        ),
                    ),
                    "execution_mode": execution_mode,
                    "response_format": response_format,
                    "messages": [
                        _message_dict(message) for message in messages
                    ],
                },
            )
        media_delivery: dict[str, Any] = {}

        async def run_agent():
            async def invoke():
                if public_stream and on_public_message is not None:
                    return await _public_stream.execute_public_agent(
                        agent,
                        messages,
                        on_public_message,
                    )
                return await agent(messages)

            original_model = getattr(agent, "model", None)
            if not public_stream and original_model is not None:
                agent.model = _public_stream.public_text_model(original_model)
            try:
                with _require_active_interaction_before_text(
                    agent,
                    read_interaction_card,
                    enabled=require_interaction,
                ):
                    result = await _execute_with_runtime_system_instruction(
                        agent,
                        instruction,
                        invoke,
                        required=instruction is not None,
                    )
            finally:
                if not public_stream and original_model is not None:
                    agent.model = original_model
            if require_interaction and (
                read_interaction_card is None
                or read_interaction_card("") is None
            ):
                raise WorkspaceOrchestrationError("orchestration_error")
            return result

        try:
            if execution_mode == "agent_loop":
                aigc_tools = _aigc_tools.build_aigc_tools(
                    grants=authorization.granted_capabilities,
                    installation_id=authorization.installation_id,
                    conversation_id=turn_request.session_id,
                    business_call=effective_business_call,
                    read_task=read_aigc_task,
                    review_input=active_safe_metadata.get("aigcReviewInput"),
                    media_delivery=media_delivery,
                )
                interaction_tools = _interaction_tools.build_interaction_tools(
                    grants=authorization.granted_capabilities,
                    installation_id=authorization.installation_id,
                    conversation_id=turn_request.session_id,
                    business_call=effective_business_call,
                    read_card=read_interaction_card,
                    diagnostic_event=lambda event_type, payload: _append_runtime_trace(
                        state_storage_root,
                        installation_id=authorization.installation_id,
                        session_id=turn_request.session_id,
                        invocation_id=invocation_id,
                        event_type=event_type,
                        payload=payload,
                    ),
                )
                if aigc_tools or interaction_tools:
                    with _aigc_tools.bind_aigc_tools(
                        agent,
                        aigc_tools,
                    ), _interaction_tools.bind_interaction_tools(
                        agent,
                        interaction_tools,
                    ), _aigc_tools.track_media_delivery(
                        agent,
                        messages,
                        media_delivery,
                    ):
                        candidate = await run_agent()
                else:
                    candidate = await run_agent()
            else:
                candidate = await _execute_internal_candidate(
                    agent,
                    messages,
                    media_delivery=media_delivery,
                    response_format=response_format,
                )
        except Exception as exc:
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="agent.execute.safe_failed",
                payload={
                    "call_number": call_number,
                    "duration_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
                    "category": type(exc).__name__,
                    **_safe_provider_error(exc),
                },
            )
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
                            0,
                            round((time.perf_counter() - started_at) * 1000),
                        ),
                        "exception_type": type(exc).__name__,
                        "error": str(exc)[:2000],
                    },
                )
            logger.exception("Internal candidate execution failed")
            raise
        if (
            execution_mode == "agent_loop"
            and not _empty_reply.public_text(candidate).strip()
        ):
            shape = _empty_reply.reply_shape(candidate)
            logger.warning("Empty Agent reply shape=%s", shape)
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
                event_type="agent.execute.empty_reply",
                payload=shape,
            )
            # Opt-in only. The direct formatter/model path explicitly disables tools;
            # never fall back to invoking Agent again if that path is unavailable.
            can_generate_text = callable(
                getattr(getattr(agent, "formatter", None), "format", None),
            ) and callable(getattr(agent, "model", None))
            if (
                arguments.get("recover_empty_reply") is True
                and can_generate_text
            ):
                try:
                    candidate = await _empty_reply.recover_empty_reply(
                        agent,
                        messages,
                        candidate,
                        _execute_internal_candidate,
                    )
                except Exception:
                    logger.exception("Text-only reply recovery failed")
                _append_runtime_trace(
                    state_storage_root,
                    installation_id=authorization.installation_id,
                    session_id=turn_request.session_id,
                    invocation_id=invocation_id,
                    event_type="agent.execute.reply_recovery",
                    payload=_empty_reply.reply_shape(candidate),
                )
        serialized = _message_dict(candidate)
        text = (
            candidate.get_text_content()
            if hasattr(candidate, "get_text_content")
            else str(serialized.get("content", ""))
        )
        try:
            parsed_json = json.loads(text)
            complete_json_object = isinstance(parsed_json, dict)
        except (ValueError, TypeError):
            complete_json_object = False
        _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=invocation_id,
            event_type="agent.execute.safe_completed",
            payload={
                "call_number": call_number,
                "duration_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
                "has_text": bool(text.strip()),
                "text_length": len(text),
                "complete_json_object": complete_json_object,
            },
        )
        result = {"message": serialized, "text": text}
        if public_stream:
            serialized["content"] = [{"type": "text", "text": text}]
            serialized["metadata"] = None
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
                        0,
                        round((time.perf_counter() - started_at) * 1000),
                    ),
                    "response_id": str(
                        getattr(candidate, "invocation_id", "")
                        or serialized.get("id", ""),
                    ),
                    "has_text": bool(text.strip()),
                    "text_length": len(text),
                    "text": text,
                    "message": serialized,
                },
            )
        return result

    actual_timeout = (
        workspace_orchestration_timeout_seconds()
        if timeout_seconds is None
        else timeout_seconds
    )

    def build_orchestrator(
        active_invocation_id: str,
        active_safe_metadata: dict[str, Any],
    ) -> "WorkspaceTurnOrchestrator":
        return WorkspaceTurnOrchestrator(
            workspace_root=workspace_root,
            config=config,
            signed_files=authorization.signed_workspace_files,
            execute_agent=lambda arguments: execute_agent(
                arguments,
                active_safe_metadata,
            ),
            session_context=lambda: trusted_context,
            business_call=effective_business_call,
            trace_sink=lambda trace: _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=active_invocation_id,
                event_type="runtime.trace",
                payload=trace,
            ),
            timeout_seconds=actual_timeout,
            public_runtime=authorization.package_type == "super_expert_public",
            signed_workspace_root=authorization.signed_workspace_root,
        )

    orchestrator = build_orchestrator(
        invocation_id,
        turn_request.safe_metadata,
    )
    try:
        result = attach_created_interactions(
            await orchestrator.invoke(turn_request, transaction),
        )
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
    if result.error_code is not None:
        try:
            failure = _failure_diagnostics.read_invocation_failure(
                storage_root=state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=invocation_id,
            )
            if failure is not None:
                result = result.model_copy(update={
                    "diagnostics": {
                        **(result.diagnostics or {}),
                        "first_failure": failure.get("first_failure"),
                    },
                })
        except _failure_diagnostics.FailureDiagnosticsUnavailable:
            logger.warning("Failed to project safe failure for invocation %s", invocation_id)
    continuation_source_request = turn_request
    last_committed_result = result if result.error_code is None else None
    continuation_pass = 0
    while (
        result.error_code is None
        and (result.diagnostics or {}).get("continuation_reason")
        == "turn_budget_exhausted"
        and continuation_pass < _MAX_AUTOMATIC_CONTINUATION_PASSES
    ):
        continuation_pass += 1
        continuation_invocation_id = uuid.uuid4().hex
        continuation_transaction = WorkspaceStateTransaction.begin(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=continuation_invocation_id,
        )
        continuation_request = continuation_source_request.model_copy(
            update={
                "invocation_id": continuation_invocation_id,
                "state_root": continuation_transaction.state_root,
                "transaction_root": continuation_transaction.transaction_root,
                # This is a host continuation signal, not a fabricated customer
                # command. Unconsumed input is restored from pending_input.
                "normalized_input": {
                    "messages": [
                        {
                            "name": "customer",
                            "role": "user",
                            "content": "",
                        },
                    ],
                },
                "safe_metadata": {
                    key: deepcopy(value)
                    for key, value in continuation_source_request.safe_metadata.items()
                    if key != "conversationReset"
                },
            },
        )
        continuation_request._runtime_continuation = True
        _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=continuation_invocation_id,
            event_type="orchestration.continuation.started",
            payload={"pass": continuation_pass},
        )
        try:
            continued = attach_created_interactions(
                await build_orchestrator(
                    continuation_invocation_id,
                    continuation_request.safe_metadata,
                ).invoke(
                    continuation_request,
                    continuation_transaction,
                ),
            )
        except asyncio.CancelledError:
            _append_runtime_trace(
                state_storage_root,
                installation_id=authorization.installation_id,
                session_id=turn_request.session_id,
                invocation_id=continuation_invocation_id,
                event_type="orchestration.cancelled",
                payload={"error_code": "cancelled"},
            )
            raise
        _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=continuation_invocation_id,
            event_type=(
                "orchestration.continuation.completed"
                if continued.error_code is None
                else "orchestration.continuation.failed"
            ),
            payload=(
                {"pass": continuation_pass}
                if continued.error_code is None
                else {
                    "pass": continuation_pass,
                    "error_code": continued.error_code,
                    "diagnostic_ref": continued.diagnostic_ref,
                }
            ),
        )
        if continued.error_code is not None:
            # Earlier passes are already committed. Never replace their safe
            # completion with a later transient failure.
            result = last_committed_result or continued
            break
        result = continued
        last_committed_result = continued
        continuation_source_request = continuation_request
    if (result.diagnostics or {}).get(
        "continuation_reason",
    ) == "turn_budget_exhausted" and continuation_pass >= _MAX_AUTOMATIC_CONTINUATION_PASSES:
        _append_runtime_trace(
            state_storage_root,
            installation_id=authorization.installation_id,
            session_id=turn_request.session_id,
            invocation_id=turn_request.invocation_id,
            event_type="orchestration.continuation.limit_reached",
            payload={"max_passes": _MAX_AUTOMATIC_CONTINUATION_PASSES},
        )
    return attach_created_interactions(result).model_copy(
        update={"invocation_id": invocation_id},
    )


class WorkspaceStateTransaction:
    """Copy-on-write state directory promoted only after valid completion."""

    def __init__(
        self,
        *,
        invocation_id: str,
        state_root: Path,
        transaction_root: Path,
        base_digest: str | None,
        installation_id: str,
        session_id: str,
        binding_path: Path,
    ) -> None:
        self.invocation_id = invocation_id
        self.state_root = state_root
        self.transaction_root = transaction_root
        self.base_digest = base_digest
        self.installation_id = installation_id
        self.session_id = session_id
        self.binding_path = binding_path
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
        transaction_root = storage / "transactions" / _scope_key(invocation_id)
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
            installation_id=installation_id,
            session_id=session_id,
            binding_path=_state_binding_path(storage, installation_id, session_id),
        )

    def commit(self) -> None:
        if self._finished or not self.transaction_root.is_dir():
            raise WorkspaceOrchestrationError("invalid_completion")
        self.state_root.parent.mkdir(parents=True, exist_ok=True)
        backup = self.state_root.with_name(
            f"{self.state_root.name}.backup-{_scope_key(self.invocation_id)[:12]}",
        )
        with _exclusive_state_lock(self.state_root.with_suffix(".lock")):
            _validate_state_binding(
                self.binding_path, self.transaction_root,
                self.installation_id, self.session_id,
            )
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
                if (
                    moved_old
                    and backup.exists()
                    and not self.state_root.exists()
                ):
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

    async def _trace_stage(self, event: str, duration_ms: int | None = None) -> None:
        if self._trace_sink is None:
            return
        payload: dict[str, Any] = {"event": event}
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        try:
            await _maybe_await(self._trace_sink({
                "invocation_id": self.request.invocation_id,
                "agent_id": self.request.agent_id,
                "session_id": self.request.session_id,
                "origin": "host",
                "payload": payload,
            }))
        except Exception:
            logger.warning("Failed to write safe host stage %s", event)

    async def call(self, capability: str, arguments: dict[str, Any]) -> Any:
        if self.completion is not None or self.failure is not None:
            raise WorkspaceOrchestrationError("invalid_completion")
        if self.request.granted_capabilities.get(capability) != "1":
            raise WorkspaceOrchestrationError("unauthorized_capability")
        if capability == "agent.execute":
            return await _maybe_await(self._execute_agent(arguments))
        if capability == "session.context":
            started_at = time.perf_counter()
            try:
                result = await _maybe_await(self._session_context())
            except Exception:
                await self._trace_stage(
                    "session.context.failed",
                    max(0, round((time.perf_counter() - started_at) * 1000)),
                )
                raise
            else:
                await self._trace_stage(
                    "session.context.completed",
                    max(0, round((time.perf_counter() - started_at) * 1000)),
                )
                return result
        if capability == "runtime.trace":
            if self._trace_sink is not None:
                await _maybe_await(
                    self._trace_sink(
                        {
                            "invocation_id": self.request.invocation_id,
                            "agent_id": self.request.agent_id,
                            "session_id": self.request.session_id,
                            "origin": "agent",
                            "payload": dict(arguments),
                        },
                    ),
                )
            return {"accepted": True}
        if capability == "runtime.failure.read/1":
            if arguments:
                raise WorkspaceOrchestrationError("orchestration_error")
            try:
                return _failure_diagnostics.read_latest_failure(
                    storage_root=self.request.transaction_root.parents[1],
                    grants=_composition.get_super_expert_platform_service().grant_repository,
                    installation_id=self.request.installation_id,
                    release_id=self.request.release_id,
                    agent_id=self.request.agent_id,
                    user_id=self.request.user_id,
                    session_id=self.request.session_id,
                    owner_resolver=_composition.resolve_event_scope,
                    exclude_invocation_id=self.request.invocation_id,
                )
            except _failure_diagnostics.FailureDiagnosticsUnauthorized as exc:
                raise WorkspaceOrchestrationError("unauthorized_capability") from exc
            except _failure_diagnostics.FailureDiagnosticsUnavailable as exc:
                raise WorkspaceOrchestrationError(
                    "orchestration_error", "failure_diagnostics_unavailable",
                ) from exc
        if capability == "runtime.complete":
            completion = WorkspaceTurnCompletion.model_validate(arguments)
            if completion.invocation_id != self.request.invocation_id:
                raise WorkspaceOrchestrationError("invalid_completion")
            self.completion = completion
            await self._trace_stage("runtime.complete.accepted")
            return {"accepted": True}
        if capability == "runtime.fail":
            failure = WorkspaceTurnFailure.model_validate(arguments)
            if failure.invocation_id != self.request.invocation_id:
                raise WorkspaceOrchestrationError("invalid_completion")
            self.failure = failure
            await self._trace_stage("runtime.fail.accepted")
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
        public_runtime: bool = False,
        signed_workspace_root: Path | None = None,
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
        self.public_runtime = public_runtime
        self.signed_workspace_root = signed_workspace_root
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
        request._runtime_deadline_monotonic = (
            loop.time() + self.timeout_seconds
        )
        request._runtime_deadline_reserve_seconds = reserve
        host = WorkspaceRuntimeHost(
            request=request,
            execute_agent=self.execute_agent,
            session_context=self.session_context,
            business_call=self.business_call,
            trace_sink=self.trace_sink,
        )
        try:
            runtime_started_at = time.perf_counter()
            await host._trace_stage("runtime.invoke.started")
            if self.public_runtime:
                if self.signed_workspace_root is None:
                    raise WorkspaceOrchestrationError("runtime_isolation_unavailable")
                try:
                    await invoke_public_runtime(
                        source_root=self.signed_workspace_root,
                        entrypoint=self.config.entrypoint,
                        request=request,
                        host=host,
                        timeout_seconds=self.timeout_seconds,
                    )
                finally:
                    await host._trace_stage(
                        "runtime.invoke.finished",
                        max(0, round((time.perf_counter() - runtime_started_at) * 1000)),
                    )
            else:
                try:
                    runtime = self._load_runtime()
                    result = runtime.handle(request, host)
                    if not inspect.isawaitable(result):
                        raise WorkspaceOrchestrationError("orchestration_error")
                    await asyncio.wait_for(result, timeout=self.timeout_seconds)
                finally:
                    await host._trace_stage(
                        "runtime.invoke.finished",
                        max(0, round((time.perf_counter() - runtime_started_at) * 1000)),
                    )
            if host.failure is not None:
                logger.error(
                    "Workspace runtime reported failure (%s)",
                    host.failure.diagnostic_ref or host.failure.error_code,
                )
                transaction.discard()
                await host._trace_stage("transaction.discarded")
                return WorkspaceTurnResult(
                    error_code=host.failure.error_code,
                    diagnostic_ref=host.failure.diagnostic_ref,
                )
            if host.completion is None:
                raise WorkspaceOrchestrationError("invalid_completion")
            _validate_render_bound_message(host.completion.message)
            transaction.commit()
            await host._trace_stage("transaction.committed")
            return WorkspaceTurnResult(
                message=host.completion.message,
                diagnostics=host.completion.diagnostics,
            )
        except asyncio.CancelledError:
            transaction.discard()
            await host._trace_stage("transaction.discarded")
            raise
        except asyncio.TimeoutError:
            transaction.discard()
            await host._trace_stage("transaction.discarded")
            return WorkspaceTurnResult(
                error_code="orchestration_timeout",
                diagnostic_ref="asyncio.TimeoutError",
            )
        except PublicRuntimeError as exc:
            transaction.discard()
            await host._trace_stage("transaction.discarded")
            return WorkspaceTurnResult(
                error_code="orchestration_error",
                diagnostic_ref=str(exc),
            )
        except WorkspaceOrchestrationError as exc:
            transaction.discard()
            await host._trace_stage("transaction.discarded")
            return WorkspaceTurnResult(
                error_code=exc.error_code,
                diagnostic_ref=(exc.diagnostic_ref or f"WorkspaceOrchestrationError:{exc.error_code}"),
            )
        except Exception as exc:
            transaction.discard()
            await host._trace_stage("transaction.discarded")
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


async def _list_aigc_capabilities(request: Any) -> dict[str, Any]:
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.app.routers.aigc_studio import build_capability_list

    _ = request
    result = await build_capability_list(ProviderManager.get_instance())
    return result.model_dump(mode="json")


async def _list_aigc_workflow_capabilities(request: Any) -> dict[str, Any]:
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.app.routers.aigc_studio import (
        build_workflow_capability_catalog,
    )

    _ = request
    result = await build_workflow_capability_catalog(
        ProviderManager.get_instance(),
    )
    return result.model_dump(mode="json")


def _retired_aigc_write_receipt(
    *,
    capability: str,
    arguments: dict[str, Any],
    platform_service: Any,
    installation_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Adapt signed legacy writes to an owned, read-only task receipt."""
    receipt: dict[str, Any] = {
        "contract": capability,
        "status": "retired",
        "write_applied": False,
        "customer_action_required": True,
    }
    binding = arguments.get("binding")
    if not isinstance(binding, dict):
        return receipt
    material_task_id = binding.get("material_task_id")
    if not isinstance(material_task_id, str) or not material_task_id:
        return receipt
    task = platform_service.get_task(material_task_id)
    if task is None:
        return receipt
    persisted_binding = task.binding.model_dump(mode="json")
    if (
        persisted_binding != binding
        or task.binding.installation_id != installation_id
        or task.binding.conversation_id != conversation_id
    ):
        return receipt
    receipt.update(
        {
            "status": task.status.value,
            "compatibility_mode": "legacy_read_only",
            "completion_source": (
                "customer" if task.status.value == "ACCEPTED" else None
            ),
            "review_performed": False,
            "material_task_id": material_task_id,
            "task_status": task.status.value,
            "customer_action_required": task.status.value != "ACCEPTED",
        },
    )
    return receipt


async def handle_workspace_turn(
    *,
    agent: Any,
    messages: list[Any],
    request: Any,
    query: str | None,
    mission_info: dict[str, Any] | None,
    agent_id: str,
    agent_name: str,
    workspace_root: Path,
    orchestration: Any,
    standard_stream: Callable[..., Any],
):
    """Execute a Super Agent turn behind the generic workspace handler SPI."""
    if not is_workspace_business_turn(query, mission_info=mission_info):
        async for msg, last in standard_stream(
            agents=[agent],
            coroutine_task=agent(messages),
        ):
            yield msg, last, True
        return

    last_stream_id = None
    memory = getattr(agent, "memory", None)
    memory_snapshot = None
    state_dict = getattr(memory, "state_dict", None)
    if callable(state_dict):
        try:
            memory_snapshot = deepcopy(state_dict())
        except Exception:
            logger.exception("Failed to snapshot workspace memory before turn")
    if memory_snapshot is None or not callable(
        getattr(memory, "load_state_dict", None),
    ):
        logger.error("Workspace memory cannot be restored for agent %s", agent_id)
        yield workspace_result_to_message(
            WorkspaceTurnResult(error_code="orchestration_error"),
            agent_name=agent_name,
        ), True, False
        return
    preflight_started_at = datetime.now(timezone.utc)
    setup_phase = "release_authorization"
    diagnostic_installation_id = None
    result = WorkspaceTurnResult(error_code="orchestration_error")
    try:
        tenant_id = str(getattr(request, "tenant_id", "local") or "local")
        authorization = resolve_active_workspace_authorization(
            agent_id=agent_id,
            workspace_root=workspace_root,
            tenant_id=tenant_id,
            config=orchestration,
        )
        diagnostic_installation_id = authorization.installation_id
        setup_phase = "state_continuity"
        from .state_continuity import StateContinuityError, ensure_state_continuity

        sealed_root = Path(WORKING_DIR) / "sealed_agents"
        record = get_sealed_agent_registry().get_agent(agent_id)
        target_grant = SuperExpertGrantRepository(sealed_root).get(
            authorization.installation_id,
        )
        if record is None or target_grant is None:
            raise WorkspaceOrchestrationError(
                "orchestration_error", "state_release_identity_mismatch",
            )
        try:
            ensure_state_continuity(
                storage_root=Path(WORKING_DIR) / "workspace_runtime_state",
                sealed_root=sealed_root,
                grants=SuperExpertGrantRepository(sealed_root),
                record=record,
                target_grant=target_grant,
                session_id=str(request.session_id),
                user_id=str(request.user_id),
            )
        except StateContinuityError as exc:
            if exc.category == "state_contract_missing":
                logger.warning(
                    "Falling back to the standard Agent turn for %s because "
                    "the release predates workspace state contracts",
                    agent_id,
                )
                async for msg, last in standard_stream(
                    agents=[agent],
                    coroutine_task=agent(messages),
                ):
                    yield msg, last, True
                return
            raise WorkspaceOrchestrationError(
                "orchestration_error", exc.category,
            ) from exc
        except Exception as exc:
            logger.exception("Workspace state continuity failed closed")
            raise WorkspaceOrchestrationError(
                "orchestration_error", "state_continuity_failed",
            ) from exc
        setup_phase = "turn_context"
        platform_service = _composition.get_super_expert_platform_service()
        platform_events = platform_service.list_session_events(
            installation_id=authorization.installation_id,
            conversation_id=str(request.session_id),
        )
        interaction_receipts = []
        interaction_service = getattr(platform_service, "interactions", None)
        if interaction_service is not None:
            cards = interaction_service.list_owned(
                installation_id=authorization.installation_id,
                conversation_ids={str(request.session_id)},
            )
            for card in sorted(cards, key=lambda item: item.updated_at)[-20:]:
                if card.status.value in {"PENDING", "SUBMITTED"}:
                    interaction_receipts.append(card_receipt(
                        card,
                        "submitted" if card.status.value == "SUBMITTED" else "created",
                    ))
        review_input = _media_review_context.current_review_input(
            user_id=str(request.user_id),
            installation_id=authorization.installation_id,
            conversation_id=str(request.session_id),
        )
        conversation_history: list[Any] = []
        memory = getattr(agent, "memory", None)
        get_memory = getattr(memory, "get_memory", None)
        if callable(get_memory):
            conversation_history = list(await get_memory(prepend_summary=True))

        from .aigc_binding import (
            compatible_installations, owned_task, resolve_existing_binding,
        )
        invocation_id = uuid.uuid4().hex

        def authorized_aigc_task(material_task_id: str):
            task = platform_service.get_task(material_task_id)
            try:
                installations = compatible_installations(
                    storage_root=Path(WORKING_DIR) / "workspace_runtime_state",
                    grants=SuperExpertGrantRepository(sealed_root),
                    agent_id=agent_id, tenant_id=tenant_id,
                    installation_id=authorization.installation_id,
                    release_id=authorization.release_id,
                    session_id=str(request.session_id),
                    user_id=str(request.user_id),
                )
            except StateContinuityError:
                return None, "unavailable", frozenset()
            if not owned_task(
                task=task, adapter=platform_service.aigc,
                user_id=str(request.user_id),
                conversation_id=str(request.session_id),
                allowed_installations=installations,
            ):
                return None, "not_found", installations
            return task, "found", installations

        async def business_call(
            capability: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            payload = dict(arguments)
            contract_version = authorization.granted_capabilities.get(
                capability,
            )
            if contract_version is None:
                raise WorkspaceOrchestrationError("unauthorized_capability")
            if capability in {
                "aigc.review.complete",
                "aigc.asset.submit",
            }:
                return _retired_aigc_write_receipt(
                    capability=capability,
                    arguments=payload,
                    platform_service=platform_service,
                    installation_id=authorization.installation_id,
                    conversation_id=str(request.session_id),
                )
            if capability == "aigc.capabilities.list/1":
                if payload:
                    raise WorkspaceOrchestrationError("orchestration_error")
                return await _list_aigc_capabilities(request)
            if capability == "aigc.workflow.capabilities.list/1":
                if payload:
                    raise WorkspaceOrchestrationError("orchestration_error")
                return await _list_aigc_workflow_capabilities(request)
            if capability == "interaction.capabilities.list/1":
                if set(payload) - {"component_types"}:
                    raise WorkspaceOrchestrationError("orchestration_error")
                return _interaction_contract.build_interaction_catalog(
                    payload.get("component_types", []),
                )
            if capability == "interaction.card.read/1":
                return platform_service.read_interaction(
                    tenant_id=tenant_id,
                    installation_id=authorization.installation_id,
                    conversation_id=str(request.session_id),
                    contract_version=contract_version,
                    arguments=payload,
                )
            if capability == "aigc.task.binding.resolve/1":
                if set(payload) - {"task_key", "content_revision"}:
                    raise WorkspaceOrchestrationError("orchestration_error")
                if (
                    ("task_key" in payload and payload["task_key"] is None)
                    or ("content_revision" in payload
                        and payload["content_revision"] is None)
                ):
                    return {"contract": capability, "status": "invalid_request"}
                _, scope_status, installations = authorized_aigc_task("")
                if scope_status == "unavailable":
                    return {"contract": capability, "status": "unavailable"}
                return resolve_existing_binding(
                    tasks=platform_service.task_repository.list_for_conversations(
                        {str(request.session_id)},
                    ),
                    adapter=platform_service.aigc,
                    user_id=str(request.user_id),
                    conversation_id=str(request.session_id),
                    allowed_installations=installations,
                    task_key=payload.get("task_key"),
                    content_revision=payload.get("content_revision"),
                )
            if capability == "aigc.task.snapshot/1":
                if set(payload) != {"material_task_id"} or not isinstance(
                    payload.get("material_task_id"), str,
                ):
                    raise WorkspaceOrchestrationError("orchestration_error")
                from .aigc_snapshot import project_owned_aigc_snapshot

                task, task_status, _ = authorized_aigc_task(
                    payload["material_task_id"],
                )
                if task is None:
                    return {"contract": capability, "status": task_status}
                return project_owned_aigc_snapshot(
                    task=task,
                    adapter=platform_service.aigc,
                    user_id=str(request.user_id),
                    installation_id=task.binding.installation_id,
                    conversation_id=str(request.session_id),
                )
            if capability == "aigc.task.assets.list/1":
                if set(payload) != {"material_task_id"} or not isinstance(
                    payload.get("material_task_id"), str,
                ):
                    raise WorkspaceOrchestrationError("orchestration_error")
                from .aigc_assets import list_owned_aigc_assets

                task, task_status, _ = authorized_aigc_task(
                    payload["material_task_id"],
                )
                if task is None:
                    return {"contract": capability, "status": task_status}
                return list_owned_aigc_assets(
                    task=task,
                    adapter=platform_service.aigc,
                    user_id=str(request.user_id),
                    installation_id=task.binding.installation_id,
                    conversation_id=str(request.session_id),
                )
            if capability == "aigc.task.assets.localize/1":
                if set(payload) != {
                    "material_task_id", "assets", "idempotency_key",
                }:
                    raise AigcLocalizationHostError(
                        stage="request_validation", code="INVALID_LOCALIZE_REQUEST",
                        responsibility="developer", recovery_action="correct_request",
                        field_path="request", constraint="FIELD_SET_MISMATCH",
                    )
                material_task_id = payload.get("material_task_id")
                idempotency_key = payload.get("idempotency_key")
                if (
                    not isinstance(material_task_id, str)
                    or not isinstance(idempotency_key, str)
                ):
                    raise AigcLocalizationHostError(
                        stage="request_validation", code="INVALID_LOCALIZE_REQUEST",
                        responsibility="developer", recovery_action="correct_request",
                        field_path="request", constraint="STRING_REQUIRED",
                    )
                if not 1 <= len(idempotency_key) <= 160:
                    raise AigcLocalizationHostError(
                        stage="request_validation", code="INVALID_IDEMPOTENCY_KEY",
                        responsibility="developer", recovery_action="correct_request",
                        field_path="idempotency_key", constraint="LENGTH_INVALID",
                    )
                try:
                    from .aigc_assets import (
                        AigcAssetSelectionError, prepare_owned_aigc_localization,
                        verify_public_aigc_localization,
                    )
                    from .local_host import dispatch_aigc_asset_localization
                    from qwenpaw.app.aigc.resource_store import AigcResourceError
                except Exception as exc:
                    _log_aigc_localization_internal_error(
                        exc, stage="host_setup", invocation_id=invocation_id,
                    )
                    raise AigcLocalizationHostError(
                        stage="host_setup", code="HOST_INTERNAL_ERROR",
                        responsibility="platform",
                        recovery_action="contact_platform_with_invocation_id",
                    ) from None

                try:
                    task, task_status, _ = authorized_aigc_task(material_task_id)
                except Exception as exc:
                    _log_aigc_localization_internal_error(
                        exc, stage="task_binding", invocation_id=invocation_id,
                    )
                    raise AigcLocalizationHostError(
                        stage="task_binding", code="HOST_INTERNAL_ERROR",
                        responsibility="platform",
                        recovery_action="contact_platform_with_invocation_id",
                    ) from None
                if task is None:
                    return {"contract": capability, "status": task_status}
                try:
                    localized_assets = prepare_owned_aigc_localization(
                        task=task,
                        adapter=platform_service.aigc,
                        user_id=str(request.user_id),
                        installation_id=task.binding.installation_id,
                        conversation_id=str(request.session_id),
                        requested_assets=payload.get("assets"),
                    )
                    await verify_public_aigc_localization(localized_assets)
                except AigcResourceError as exc:
                    request_issue = exc.code in {
                        "ASSET_NOT_FOUND", "ASSET_BINDING_MISMATCH",
                    }
                    raise AigcLocalizationHostError(
                        stage="asset_validation", code=(
                            exc.code if exc.code in {
                                "ASSET_NOT_FOUND", "ASSET_BINDING_MISMATCH",
                                "ASSET_FILE_NOT_FOUND",
                                "ASSET_PUBLIC_DOWNLOAD_UNAVAILABLE",
                            } else "HOST_INTERNAL_ERROR"
                        ), responsibility="developer" if request_issue else "platform",
                        recovery_action=(
                            "refresh_asset_list_and_correct_request" if request_issue
                            else "contact_platform_with_invocation_id"
                        ),
                        field_path="assets" if request_issue else "not_recorded",
                        constraint="OWNED_ASSET_REQUIRED" if request_issue else "not_recorded",
                    ) from None
                except AigcAssetSelectionError:
                    raise AigcLocalizationHostError(
                        stage="asset_validation", code="INVALID_ASSET_SELECTION",
                        responsibility="developer", recovery_action="correct_request",
                        field_path="assets", constraint="SELECTION_INVALID",
                    ) from None
                except Exception as exc:
                    _log_aigc_localization_internal_error(
                        exc, stage="asset_preparation", invocation_id=invocation_id,
                    )
                    raise AigcLocalizationHostError(
                        stage="asset_preparation", code="HOST_INTERNAL_ERROR",
                        responsibility="platform",
                        recovery_action="contact_platform_with_invocation_id",
                    ) from None
                try:
                    return await dispatch_aigc_asset_localization(
                        material_task_id=material_task_id,
                        assets=localized_assets,
                        idempotency_key=idempotency_key,
                        tenant_id=tenant_id,
                        user_id=str(request.user_id),
                        session_id=str(request.session_id),
                        agent_id=agent_id,
                        agent_name=agent_name,
                        installation_id=authorization.installation_id,
                        release_id=authorization.release_id,
                        invocation_id=invocation_id,
                    )
                except Exception as exc:
                    _log_aigc_localization_internal_error(
                        exc, stage="task_dispatch", invocation_id=invocation_id,
                    )
                    raise AigcLocalizationHostError(
                        stage="task_dispatch", code="HOST_INTERNAL_ERROR",
                        responsibility="platform",
                        recovery_action="contact_platform_with_invocation_id",
                    ) from None
            if capability in {
                "local.task.start/1", "local.task.read/1", "local.task.cancel/1",
            }:
                from .local_host import dispatch_local_task

                return await dispatch_local_task(
                    capability=capability,
                    arguments=payload,
                    tenant_id=tenant_id,
                    user_id=str(request.user_id),
                    session_id=str(request.session_id),
                    agent_id=agent_id,
                    installation_id=authorization.installation_id,
                    release_id=authorization.release_id,
                    invocation_id=invocation_id,
                    granted_capabilities=tuple(authorization.granted_capabilities),
                )
            if capability == "local.task.outputs.bind/1":
                from .local_host import bind_localized_task_outputs

                try:
                    compatible = compatible_installations(
                        storage_root=Path(WORKING_DIR) / "workspace_runtime_state",
                        grants=SuperExpertGrantRepository(sealed_root),
                        agent_id=agent_id, tenant_id=tenant_id,
                        installation_id=authorization.installation_id,
                        release_id=authorization.release_id,
                        session_id=str(request.session_id),
                        user_id=str(request.user_id),
                    )
                except StateContinuityError:
                    return {"contract": capability, "status": "unavailable"}
                grant_repository = SuperExpertGrantRepository(sealed_root)
                return await bind_localized_task_outputs(
                    arguments=payload,
                    tenant_id=tenant_id, user_id=str(request.user_id),
                    session_id=str(request.session_id), agent_id=agent_id,
                    installation_id=authorization.installation_id,
                    release_id=authorization.release_id,
                    invocation_id=invocation_id,
                    compatible_installation_releases={
                        item: grant_repository.get(item).release_id
                        for item in compatible
                    },
                )
            idempotency_key = str(payload.pop("idempotency_key", ""))
            if not idempotency_key:
                raise WorkspaceOrchestrationError("orchestration_error")
            if capability in {
                "interaction.card.create/1",
                "interaction.card.cancel/1",
            }:
                return await platform_service.execute_interaction(
                    tenant_id=tenant_id,
                    installation_id=authorization.installation_id,
                    conversation_id=str(request.session_id),
                    capability=capability,
                    contract_version=contract_version,
                    arguments=payload,
                    idempotency_key=idempotency_key,
                )
            return await platform_service.execute(
                tenant_id=tenant_id,
                user_id=str(getattr(request, "user_id", "") or ""),
                installation_id=authorization.installation_id,
                capability=capability,
                contract_version=contract_version,
                arguments=payload,
                idempotency_key=idempotency_key,
            )

        def read_aigc_task(material_task_id: str) -> dict[str, Any] | None:
            task = platform_service.task_repository.get(material_task_id)
            if task is None:
                return None
            task_binding = task.binding.model_dump(mode="json")
            trusted_review_binding = (
                review_input.get("binding")
                if review_input is not None
                else None
            )
            installation_matches = (
                task.binding.installation_id == authorization.installation_id
                or task_binding == trusted_review_binding
            )
            if (
                not installation_matches
                or task.binding.conversation_id != str(request.session_id)
            ):
                return None
            return task.model_dump(mode="json")

        def read_interaction_card(
            interaction_id: str,
        ) -> dict[str, Any] | None:
            interactions = platform_service.interactions
            if interactions is None:
                return None
            try:
                if interaction_id:
                    card = interactions.get_owned(
                        interaction_id,
                        installation_id=authorization.installation_id,
                        conversation_id=str(request.session_id),
                    )
                else:
                    cards = interactions.list_owned(
                        installation_id=authorization.installation_id,
                        conversation_ids={str(request.session_id)},
                    )
                    card = next(
                        (
                            item
                            for item in reversed(cards)
                            if item.status.value == "PENDING"
                            and item.input_policy.value == "card_only"
                        ),
                        None,
                    )
                    if card is None:
                        return None
            except Exception:
                return None
            return card.model_dump(mode="json")

        async for completed, value in _public_stream.stream_workspace_turn(
            run_turn=run_workspace_orchestration_turn,
            agent=agent,
            original_messages=messages,
            conversation_history=conversation_history,
            request=request,
            agent_id=agent_id,
            workspace_root=workspace_root,
            state_storage_root=Path(WORKING_DIR) / "workspace_runtime_state",
            config=orchestration,
            authorization=authorization,
            business_call=business_call,
            read_aigc_task=read_aigc_task,
            read_interaction_card=read_interaction_card,
            interaction_receipts=interaction_receipts,
            invocation_id=invocation_id,
            safe_metadata={
                "platformEvents": [
                    event.model_dump(mode="json") for event in platform_events
                ],
                **(
                    {"aigcReviewInput": review_input}
                    if review_input is not None
                    else {}
                ),
            },
        ):
            if completed:
                result = value
            else:
                last_stream_id = value.id
                yield value, False, True
    except WorkspaceOrchestrationError as exc:
        logger.exception(
            "Workspace orchestration failed closed for agent %s",
            agent_id,
        )
        try:
            record = get_sealed_agent_registry().get_agent(agent_id)
            release = record.active_release if record is not None else None
            if release is not None:
                sealed_root = Path(WORKING_DIR) / "sealed_agents"
                grant = SuperExpertGrantRepository(sealed_root).find_release_grant(
                    agent_id, release, tenant_id=tenant_id,
                )
                if grant is not None:
                    diagnostic_installation_id = grant.installation_id
                    preflight_invocation_id = f"preflight-{uuid.uuid4().hex}"
                    _append_runtime_trace(
                        Path(WORKING_DIR) / "workspace_runtime_state",
                        installation_id=grant.installation_id,
                        session_id=str(request.session_id),
                        invocation_id=preflight_invocation_id,
                        event_type="orchestration.preflight_failed",
                        payload={
                            "started_at": preflight_started_at.isoformat(),
                            "phase": setup_phase,
                            "category": exc.diagnostic_ref or exc.error_code,
                            "error_code": exc.error_code,
                        },
                    )
                    result = WorkspaceTurnResult(
                        error_code="orchestration_error",
                        invocation_id=preflight_invocation_id,
                        diagnostics={"first_failure": {
                            "phase": setup_phase,
                            "category": _failure_diagnostics._token(exc.diagnostic_ref or exc.error_code),
                            "attempt": None,
                        }},
                    )
        except Exception:
            logger.exception("Failed to record workspace preflight failure")
    except BaseException:
        restore_memory = getattr(memory, "load_state_dict", None)
        if memory_snapshot is not None and callable(restore_memory):
            try:
                restore_memory(deepcopy(memory_snapshot), strict=False)
            except Exception:
                logger.exception("Failed to restore workspace memory after exception")
        raise

    response_message = workspace_result_to_message(
        result,
        agent_name=agent_name,
    )
    if last_stream_id is not None:
        response_message.id = last_stream_id
    should_save_session = True
    restore_memory = getattr(memory, "load_state_dict", None)
    try:
        restore_memory(deepcopy(memory_snapshot), strict=False)
    except Exception:
        logger.exception("Failed to restore workspace memory after turn")
        should_save_session = False
    add_to_memory = getattr(memory, "add", None)
    if should_save_session and callable(add_to_memory):
        for message in messages:
            await add_to_memory(message)
        await add_to_memory(response_message)
    if (
        result.error_code is not None
        and diagnostic_installation_id is not None
        and result.invocation_id is not None
    ):
        try:
            _append_runtime_trace(
                Path(WORKING_DIR) / "workspace_runtime_state",
                installation_id=diagnostic_installation_id,
                session_id=str(request.session_id),
                invocation_id=result.invocation_id,
                event_type="orchestration.message_staged",
                payload={"assistant_message_id": str(response_message.id)},
            )
        except Exception:
            logger.exception("Failed to record workspace message staging")
    yield response_message, True, should_save_session
