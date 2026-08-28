# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

import logging
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Literal, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel

from .buffer import _UsageEvent
from .manager import get_token_usage_manager


logger = logging.getLogger(__name__)


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
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
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
            meter_call = self._meter.before_call(
                provider_id=self._provider_id,
                model_key=self.model_name,
                messages=messages,
                max_output_tokens=_max_output_tokens(kwargs),
                item_key=billing_item_key,
            )
        try:
            result = await self._model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )
        except Exception as exc:
            if meter_call is not None:
                self._meter.record_exception(meter_call, exc)
            raise

        if isinstance(result, AsyncGenerator):
            return self._wrap_stream(result, meter_call)
        if meter_call is not None:
            self._meter.record_response(meter_call, result)
        self._record_usage(getattr(result, "usage", None))
        return result

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        meter_call: Any | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        last_usage: ChatUsage | None = None
        last_chunk: ChatResponse | None = None
        try:
            async for chunk in stream:
                last_chunk = chunk
                if getattr(chunk, "usage", None) is not None:
                    last_usage = chunk.usage
                yield chunk
        except Exception as exc:
            if meter_call is not None:
                self._meter.record_exception(meter_call, exc)
            raise
        if meter_call is not None:
            self._meter.record_response(meter_call, last_chunk)
        self._record_usage(last_usage)


def _max_output_tokens(kwargs: dict[str, Any]) -> int | None:
    value = kwargs.get("max_output_tokens", kwargs.get("max_tokens"))
    return value if isinstance(value, int) else None
