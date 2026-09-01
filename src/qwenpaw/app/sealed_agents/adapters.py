"""Trusted registry for server-owned sealed runtime adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agentscope.message import Msg

from .harness_protocol import HarnessProcess
from .request_context import SealedAdapterRequest
from .runtime import PinnedSealedRuntime


class UnsupportedSealedRuntime(ValueError):
    """A signed package requested a runtime contract this server cannot run."""


class SealedHarnessExecutionError(RuntimeError):
    """A public-safe fail-closed Harness execution failure."""


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
                return_debug = (
                    request.trusted_context.get("debug_endpoint_authorized") is True
                    and request.metadata.get("luyu_debug") is True
                )
                if return_debug and isinstance(state.get("debug"), dict):
                    public[-1].metadata = {
                        **(getattr(public[-1], "metadata", None) or {}),
                        "sealed_runtime_debug": state["debug"],
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
    ("sealed_entrypoint", "1"): _ReservedRuntimeAdapter(
        "sealed_entrypoint",
        "1",
    ),
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
