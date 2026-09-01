"""Trusted registry for server-owned sealed runtime adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
import uuid

from agentscope.message import Msg

from .entrypoint_protocol import (
    EntrypointProtocolError,
    RuntimeInvoke,
    SealedEntrypointProcess,
)
from .harness_protocol import HarnessProcess
from .request_context import SealedAdapterRequest
from .runtime import PinnedSealedRuntime


class UnsupportedSealedRuntime(ValueError):
    """A signed package requested a runtime contract this server cannot run."""


class SealedHarnessExecutionError(RuntimeError):
    """A public-safe fail-closed Harness execution failure."""


class SealedRuntimeExecutionError(RuntimeError):
    """A public-safe fail-closed sealed runtime execution failure."""


class SealedRuntimeAdapter(Protocol):
    @property
    def key(self) -> tuple[str, str]: ...

    async def run(
        self,
        *,
        pinned: Any,
        request: Any,
        model_executor: Any,
    ) -> AsyncIterator[Any]: ...


@dataclass(frozen=True)
class _ReservedRuntimeAdapter:
    """Registry placeholder replaced by the concrete execution implementation."""

    adapter: str
    contract_version: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.adapter, self.contract_version)

    async def run(
        self,
        *,
        pinned: Any,
        request: Any,
        model_executor: Any,
    ) -> AsyncIterator[Any]:
        raise UnsupportedSealedRuntime("sealed runtime adapter is not executable")
        yield  # pragma: no cover


def _message_payload(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        raw = message.model_dump(mode="json")
        return raw if isinstance(raw, dict) else {"content": str(raw)}
    return {
        "name": str(getattr(message, "name", "assistant")),
        "role": str(getattr(message, "role", "assistant")),
        "content": getattr(message, "content", str(message)),
    }


def _public_message(value: object, *, default_name: str) -> Msg:
    if not isinstance(value, dict):
        raise SealedHarnessExecutionError("sealed harness returned an invalid message")
    role = value.get("role", "assistant")
    content = value.get("content", value.get("text"))
    if role != "assistant" or not isinstance(content, (str, list)):
        raise SealedHarnessExecutionError("sealed harness returned an invalid message")
    return Msg(
        name=str(value.get("name") or default_name),
        role="assistant",
        content=content,
    )


def _message_text(message: Any) -> str:
    getter = getattr(message, "get_text_content", None)
    if callable(getter):
        value = getter()
        return value if isinstance(value, str) else str(value)
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or item.get("content") or "")
            for item in content
            if isinstance(item, dict)
        )
    return str(content)


def _controlled_messages(value: object) -> tuple[Msg, ...]:
    if not isinstance(value, list) or not value:
        raise SealedRuntimeExecutionError(
            "sealed entrypoint requested invalid model messages",
        )
    messages: list[Msg] = []
    for item in value:
        if not isinstance(item, dict):
            raise SealedRuntimeExecutionError(
                "sealed entrypoint requested invalid model messages",
            )
        role = str(item.get("role") or "")
        content = item.get("content")
        if role not in {"user", "assistant", "system"} or not isinstance(
            content,
            (str, list),
        ):
            raise SealedRuntimeExecutionError(
                "sealed entrypoint requested invalid model messages",
            )
        messages.append(
            Msg(
                name=str(item.get("name") or role),
                role=role,
                content=content,
            ),
        )
    return tuple(messages)


class SealedEntrypointAdapterV1:
    key = ("sealed_entrypoint", "1")

    def __init__(
        self,
        *,
        process_factory: Callable[[PinnedSealedRuntime, Path], Any] | None = None,
    ) -> None:
        self._process_factory = process_factory or (
            lambda pinned, session_root: SealedEntrypointProcess(
                pinned,
                session_root=session_root,
            )
        )

    async def run(
        self,
        *,
        pinned: PinnedSealedRuntime,
        request: SealedAdapterRequest,
        model_executor: Any,
    ) -> AsyncIterator[tuple[Msg, bool]]:
        if request.session_root is None:
            raise SealedRuntimeExecutionError(
                "sealed entrypoint session storage is unavailable",
            )
        messages = tuple(request.messages)
        latest = messages[-1] if messages else None
        invocation_id = str(
            request.trusted_context.get("invocation_id") or uuid.uuid4().hex,
        )
        runtime_request = RuntimeInvoke.model_validate(
            {
                "type": "runtime.invoke",
                "protocol_version": "1",
                "invocation_id": invocation_id,
                "message_id": str(getattr(latest, "id", None) or uuid.uuid4().hex),
                "release": {
                    "release_id": pinned.release_id,
                    "version": pinned.version,
                    "content_digest": pinned.content_digest,
                },
                "session": {
                    "conversation_id": str(
                        request.trusted_context.get("session_id") or "unknown",
                    ),
                    "user_id": str(
                        request.trusted_context.get("user_id") or "unknown",
                    ),
                    "channel": str(
                        request.trusted_context.get("channel") or "unknown",
                    ),
                },
                "input": {
                    "role": "user",
                    "content": _message_text(latest) if latest is not None else "",
                    "attachments": [],
                },
                "metadata": request.metadata,
                "history": [_message_payload(item) for item in messages],
                "runtime": {
                    "diagnostics_authorized": request.diagnostics_authorized,
                    "capabilities": ["agent.execute"],
                },
            },
        )

        async def host_handler(
            capability: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            if capability != "agent.execute":
                raise SealedRuntimeExecutionError(
                    "sealed entrypoint requested an unsupported capability",
                )
            controlled_messages = _controlled_messages(arguments.get("messages"))
            instruction = arguments.get("instruction")
            controlled_context = (
                {"model_instruction": instruction.strip()}
                if isinstance(instruction, str) and instruction.strip()
                else {}
            )
            draft: list[dict[str, Any]] = []
            last_text = ""
            async for message, _last in model_executor(
                controlled_messages,
                controlled_context,
            ):
                draft.append(_message_payload(message))
                text = _message_text(message)
                if text.strip():
                    last_text = text
            return {"messages": draft, "reply": last_text}

        try:
            async with self._process_factory(
                pinned,
                request.session_root,
            ) as process:
                final = await process.invoke(runtime_request, host_handler)
        except SealedRuntimeExecutionError:
            raise
        except EntrypointProtocolError as exc:
            raise SealedRuntimeExecutionError(
                "sealed entrypoint execution failed",
            ) from exc
        except Exception as exc:
            raise SealedRuntimeExecutionError(
                "sealed entrypoint execution failed",
            ) from exc

        public = Msg(
            name=pinned.agent_id,
            role="assistant",
            content=final.reply,
        )
        if request.diagnostics_authorized and final.diagnostics is not None:
            public.metadata = {
                "sealed_runtime_diagnostics": {
                    "runtime": {
                        "release_id": pinned.release_id,
                        "version": pinned.version,
                        "content_digest": pinned.content_digest,
                        "adapter": pinned.adapter_key[0],
                        "contract_version": pinned.adapter_key[1],
                    },
                    "agent": final.diagnostics,
                },
            }
        yield public, True


class SealedHarnessAdapterV1:
    key = ("sealed_harness", "1")

    def __init__(
        self,
        *,
        harness_factory: Callable[[PinnedSealedRuntime], Any] = HarnessProcess,
    ) -> None:
        self._harness_factory = harness_factory

    async def run(
        self,
        *,
        pinned: PinnedSealedRuntime,
        request: SealedAdapterRequest,
        model_executor: Any,
    ) -> AsyncIterator[tuple[Msg, bool]]:
        try:
            async with self._harness_factory(pinned) as harness:
                state: dict[str, Any] = {
                    "messages": [_message_payload(item) for item in request.messages],
                    "trusted_context": request.trusted_context,
                    "metadata": request.metadata,
                }
                for stage in (
                    "prepare_interaction",
                    "controller_gate",
                    "required_skill_dispatch",
                ):
                    state = (await harness.invoke(stage, state)).payload
                capability = state.get("capability", "model_execution")
                if capability != "model_execution":
                    raise SealedHarnessExecutionError(
                        "sealed harness requested an unsupported capability",
                    )
                draft: list[dict[str, Any]] = []
                async for message, _last in model_executor(
                    request.messages,
                    state,
                ):
                    draft.append(_message_payload(message))
                state = {
                    **state,
                    "draft_messages": draft,
                }
                for stage in ("completion_validation", "commit", "render_bound"):
                    state = (await harness.invoke(stage, state)).payload
                rendered = state.get("messages")
                if rendered is None and "text" in state:
                    rendered = [{"role": "assistant", "content": state["text"]}]
                if not isinstance(rendered, list) or not rendered:
                    raise SealedHarnessExecutionError(
                        "sealed harness returned no render-bound output",
                    )
                public = [
                    _public_message(item, default_name=pinned.agent_id)
                    for item in rendered
                ]
                return_debug = request.diagnostics_authorized
                if return_debug and isinstance(state.get("debug"), dict):
                    public[-1].metadata = {
                        **(getattr(public[-1], "metadata", None) or {}),
                        "sealed_runtime_diagnostics": state["debug"],
                    }
                for index, message in enumerate(public):
                    yield message, index == len(public) - 1
        except SealedHarnessExecutionError:
            raise
        except Exception as exc:
            raise SealedHarnessExecutionError("sealed harness execution failed") from exc


_ADAPTERS: dict[tuple[str, str], SealedRuntimeAdapter] = {
    ("standard", "1"): _ReservedRuntimeAdapter("standard", "1"),
    ("sealed_harness", "1"): SealedHarnessAdapterV1(),
    ("sealed_entrypoint", "1"): SealedEntrypointAdapterV1(),
}


def get_runtime_adapter(adapter: str, contract_version: str) -> SealedRuntimeAdapter:
    try:
        return _ADAPTERS[(adapter, contract_version)]
    except KeyError as exc:
        raise UnsupportedSealedRuntime(
            "sealed runtime adapter is not supported",
        ) from exc


def register_runtime_adapter(adapter: SealedRuntimeAdapter) -> None:
    """Install a server-owned implementation for an already allowlisted key."""
    if adapter.key not in _ADAPTERS:
        raise UnsupportedSealedRuntime("sealed runtime adapter is not allowlisted")
    _ADAPTERS[adapter.key] = adapter
