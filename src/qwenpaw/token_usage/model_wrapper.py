# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

import inspect
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel

from .buffer import _UsageEvent
from .manager import get_token_usage_manager
from ..app.billing.supplier_reference_sidecar import pop_supplier_reference


logger = logging.getLogger(__name__)


class UnsupportedBillingProviderError(RuntimeError):
    """An enforced OpenAPI call lacks a safe provider cap adapter."""


class TokenRecordingModelWrapper(ChatModelBase):
    """Wraps a ChatModelBase to record token usage on each call."""

    _usage_by_session: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        provider_id: str,
        model: ChatModelBase,
        *,
        meter: Any | None = None,
    ) -> None:
        super().__init__(
            model_name=getattr(model, "model_name", "unknown"),
            stream=getattr(model, "stream", True),
        )
        self._model = model
        self._provider_id = provider_id
        self._meter = meter

    def _record_usage(self, usage: ChatUsage | None) -> None:
        """Enqueue a usage event synchronously — never blocks the caller."""
        if usage is None:
            return
        pt = getattr(usage, "input_tokens", 0) or 0
        ct = getattr(usage, "output_tokens", 0) or 0
        if pt <= 0 and ct <= 0:
            return

        from ..app.agent_context import get_current_user_id

        user_id = get_current_user_id()

        event = _UsageEvent(
            provider_id=self._provider_id,
            model_name=self.model_name,
            prompt_tokens=pt,
            completion_tokens=ct,
            date_str=date.today().isoformat(),
            now_iso=datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds",
            ),
            user_id=user_id,
        )
        usage_data = {
            "provider_id": self._provider_id,
            "model_name": self.model_name,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        }
        self._store_usage(usage_data)
        # Analytics is explicitly best-effort.  Financial settlement happens
        # earlier in ``__call__`` and must never be undone by queue pressure.
        try:
            get_token_usage_manager().enqueue(event)
        except Exception:  # pragma: no cover - manager logs queue loss itself
            logger.warning(
                "token_usage: analytics event was dropped",
                exc_info=True,
            )

    @classmethod
    def pop_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        return cls._usage_by_session.pop(session_id, None)

    def _store_usage(self, usage: dict[str, Any] | None) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        if session_id and usage:
            TokenRecordingModelWrapper._usage_by_session[session_id] = usage

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        # Fix: Omit tool_choice="auto" for vLLM compatibility
        # vLLM without --enable-auto-tool-choice will reject requests when
        # tool_choice="auto" is present, even if tools are provided.
        # By omitting tool_choice when it's "auto", we bypass the check
        # while keeping tools available for correct tool calling behavior.
        if tool_choice == "auto":
            tool_choice = None

        billing_item_key = kwargs.pop("_billing_item_key", None)
        meter_call = None
        if self._meter is not None:
            prepared_call = _prepare_provider_call(
                self._model,
                kwargs,
                self._meter.platform_max_output_tokens,
            )
            if (
                not prepared_call.supported
                and _is_enforced_openapi_billing_context()
            ):
                raise UnsupportedBillingProviderError(
                    "cannot enforce billing for an unknown provider adapter",
                )
            meter_call = self._meter.before_call(
                provider_id=self._provider_id,
                model_key=self.model_name,
                messages=messages,
                max_output_tokens=prepared_call.max_output_tokens,
                item_key=billing_item_key,
            )
            if meter_call is not None:
                self._meter.mark_provider_call_started(meter_call)
                if prepared_call.supported:
                    kwargs = prepared_call.kwargs
        try:
            result = await self._model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )
        except BaseException as exc:
            if meter_call is not None:
                _record_exception_without_masking(self._meter, meter_call, exc)
            raise

        if _is_async_iterable(result):
            return _MeteredAsyncIterator(
                result,
                meter=self._meter,
                call=meter_call,
                record_usage=self._record_usage,
            )
        if meter_call is not None:
            self._meter.record_response(meter_call, result)
        else:
            # Adapters may have supplied private evidence even outside an
            # OpenAPI scope.  Do not retain it past the public return edge.
            pop_supplier_reference(result)
        self._record_usage(getattr(result, "usage", None))
        return result


@dataclass
class _PreparedProviderCall:
    """The frozen provider-specific output cap and valid call arguments."""

    max_output_tokens: int
    kwargs: dict[str, Any]
    supported: bool = True


class _MeteredAsyncIterator(AsyncIterator[ChatResponse]):
    """Finalize a contacted supplier stream even before first iteration."""

    def __init__(
        self,
        stream: AsyncIterator[ChatResponse],
        *,
        meter: Any | None,
        call: Any | None,
        record_usage: Any,
    ) -> None:
        self._stream = stream
        self._iterator = stream.__aiter__()
        self._meter = meter
        self._call = call
        self._record_usage = record_usage
        self._last_chunk: ChatResponse | None = None
        self._last_usage: ChatUsage | None = None
        self._owner_terminal = False
        self._financial_finalized = False
        self._iterator_closed = False
        self._iterable_closed = False

    def __aiter__(self) -> "_MeteredAsyncIterator":
        return self

    async def __anext__(self) -> ChatResponse:
        if self._owner_terminal:
            raise StopAsyncIteration
        try:
            chunk = await self._iterator.__anext__()
        except StopAsyncIteration as outcome:
            self._owner_terminal = True
            try:
                self._finish_success()
            except BaseException as finalization_error:
                await self._close_transport(finalization_error)
                raise
            await self._close_transport(outcome)
            raise
        except BaseException as exc:
            self._owner_terminal = True
            self._finish_interrupted(exc)
            await self._close_transport(exc)
            raise
        self._last_chunk = chunk
        if self._meter is not None:
            self._meter.observe_stream_chunk(self._call, chunk)
        else:
            pop_supplier_reference(chunk)
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self._last_usage = usage
        return chunk

    async def aclose(self) -> None:
        self._owner_terminal = True
        active_error: BaseException | None = None
        try:
            self._finish_interrupted(
                RuntimeError("provider stream interrupted"),
            )
        except BaseException as exc:
            active_error = exc
            raise
        finally:
            await self._close_transport(active_error)

    def _finish_success(self) -> None:
        if self._financial_finalized:
            return
        self._financial_finalized = True
        if self._meter is not None:
            self._meter.record_response(self._call, self._last_chunk)
        self._record_usage(self._last_usage)

    def _finish_interrupted(self, error: BaseException) -> None:
        if self._financial_finalized:
            return
        self._financial_finalized = True
        if self._meter is not None:
            _record_exception_without_masking(self._meter, self._call, error)

    async def _close_transport(
        self,
        active_error: BaseException | None,
    ) -> None:
        """Best-effort close each distinct provider owner exactly once."""
        cleanup_errors: list[BaseException] = []
        if not self._iterator_closed:
            self._iterator_closed = True
            error = await _close_async_resource(
                self._iterator,
                "iterator",
                active_error,
            )
            if error is not None:
                cleanup_errors.append(error)

        if self._stream is self._iterator:
            self._iterable_closed = True
        elif not self._iterable_closed:
            self._iterable_closed = True
            error = await _close_async_resource(
                self._stream,
                "iterable",
                active_error,
            )
            if error is not None:
                cleanup_errors.append(error)

        if active_error is None:
            for cleanup_error in cleanup_errors:
                if not isinstance(cleanup_error, Exception):
                    raise cleanup_error


async def _close_async_resource(
    resource: Any,
    owner_kind: str,
    active_error: BaseException | None,
) -> BaseException | None:
    """Close one provider stream owner without masking an active outcome."""
    try:
        close = getattr(resource, "aclose", None)
    except (AttributeError, KeyError, TypeError):
        return None
    if not callable(close):
        return None
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except BaseException as cleanup_error:
        logger.warning(
            "provider stream %s cleanup failed; preserving %s",
            owner_kind,
            (
                type(active_error).__name__
                if active_error is not None
                else "stream outcome"
            ),
            exc_info=(
                type(cleanup_error),
                cleanup_error,
                cleanup_error.__traceback__,
            ),
        )
        return cleanup_error
    return None


def _record_exception_without_masking(
    meter: Any,
    call: Any,
    error: BaseException,
) -> None:
    """Record supplier uncertainty without replacing caller cancellation."""
    try:
        meter.record_exception(call, error)
    except Exception:
        logger.exception("billing: exception outcome requires reconciliation")


def _is_async_iterable(value: Any) -> bool:
    """Avoid AgentScope DictMixin's KeyError for absent magic attributes."""
    try:
        return callable(getattr(value, "__aiter__"))
    except (AttributeError, KeyError, TypeError):
        return False


def _is_enforced_openapi_billing_context() -> bool:
    """Only enforced OpenAPI traffic must fail closed for unknown adapters."""
    # Keep this import local: agent_context's normal startup graph eventually
    # imports model_factory, which imports this wrapper.
    from ..app.agent_context import get_current_billing_context
    from ..app.billing.open_api import OpenApiBillingSession

    context = get_current_billing_context()
    return (
        isinstance(context, OpenApiBillingSession)
        and context.mode == "enforced"
    )


def _prepare_provider_call(
    model: Any,
    call_kwargs: Mapping[str, Any],
    platform_cap: int,
) -> _PreparedProviderCall:
    """Freeze a cap and only send the field valid for this provider API."""
    kind = _provider_kind(model)
    model_kwargs = _mapping_value(model, "generate_kwargs")
    kwargs = dict(call_kwargs)
    if kind in {"openai", "anthropic"}:
        cap = _minimum_limit(
            platform_cap,
            _flat_limits(call_kwargs),
            _flat_limits(model_kwargs),
            [_safe_limit(getattr(model, "max_tokens", None))],
        )
        kwargs.pop("max_output_tokens", None)
        kwargs["max_tokens"] = cap
        return _PreparedProviderCall(cap, kwargs)
    if kind == "gemini":
        cap = _minimum_limit(
            platform_cap,
            _flat_limits(call_kwargs),
            _flat_limits(model_kwargs),
        )
        kwargs.pop("max_tokens", None)
        kwargs["max_output_tokens"] = cap
        return _PreparedProviderCall(cap, kwargs)
    if kind == "ollama":
        model_options = _mapping_value(model, "options")
        cap = _minimum_limit(
            platform_cap,
            _flat_limits(call_kwargs),
            _ollama_limits(call_kwargs),
            _flat_limits(model_kwargs),
            _ollama_limits(model_kwargs),
            [_safe_limit(model_options.get("num_predict"))],
        )
        kwargs.pop("max_tokens", None)
        kwargs.pop("max_output_tokens", None)
        options = dict(model_options)
        options.update(_mapping_value(model_kwargs, "options"))
        options.update(_mapping_value(call_kwargs, "options"))
        options["num_predict"] = cap
        kwargs["options"] = options
        return _PreparedProviderCall(cap, kwargs)

    # Do not strip potentially valid provider arguments if we cannot prove
    # their native contract.  Enforced OpenAPI callers reject this prior to
    # reservation; observe/off/non-OpenAPI preserve their old behaviour.
    return _PreparedProviderCall(platform_cap, kwargs, supported=False)


def _provider_kind(model: Any) -> str | None:
    explicit = getattr(model, "billing_provider_kind", None)
    if explicit in {"openai", "anthropic", "gemini", "ollama"}:
        return explicit
    module = type(model).__module__
    name = type(model).__name__
    if module.startswith("agentscope.model"):
        if "OpenAI" in name:
            return "openai"
        if "Anthropic" in name:
            return "anthropic"
        if "Gemini" in name:
            return "gemini"
        if "Ollama" in name:
            return "ollama"
    return None


def _mapping_value(value: Any, field_name: str) -> Mapping[str, Any]:
    candidate = (
        value.get(field_name)
        if isinstance(value, Mapping)
        else getattr(value, field_name, {})
    )
    return candidate if isinstance(candidate, Mapping) else {}


def _flat_limits(values: Mapping[str, Any]) -> list[int | None]:
    return [
        _safe_limit(values.get(key))
        for key in ("max_tokens", "max_output_tokens")
    ]


def _ollama_limits(values: Mapping[str, Any]) -> list[int | None]:
    return [
        _safe_limit(_mapping_value(values, "options").get("num_predict")),
    ]


def _safe_limit(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _minimum_limit(platform_cap: int, *groups: list[int | None]) -> int:
    limits = [platform_cap]
    for group in groups:
        limits.extend(limit for limit in group if limit is not None)
    return min(limits)
