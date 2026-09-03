# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from openai import NOT_GIVEN
from pydantic import BaseModel

from qwenpaw.providers.openai_chat_model_compat import (
    OpenAIChatModelCompat,
    _sanitize_tool_call,
)
from qwenpaw.providers.openai_response_diagnostics import (
    capture_openai_response_diagnostics,
    pop_openai_response_diagnostics,
)


class CompatHarnessOpenAIChatModel(OpenAIChatModelCompat):
    async def parse_stream_for_test(
        self,
        start_datetime: datetime,
        stream: Any,
    ) -> list[Any]:
        responses = []
        async for response in self._parse_openai_stream_response(
            start_datetime,
            stream,
        ):
            responses.append(response)
        return responses


class FakeAsyncStream:
    def __init__(self, items: list[Any]):
        self._items = items
        self._iter = None

    async def __aenter__(self) -> "FakeAsyncStream":
        self._iter = iter(self._items)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def __aiter__(self) -> "FakeAsyncStream":
        return self

    async def __anext__(self) -> Any:
        assert self._iter is not None
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _StopAfterCapture(RuntimeError):
    pass


class _CapturingCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        raise _StopAfterCapture


class _InternalResult(BaseModel):
    query: str


def _make_chunk(tool_calls: list[Any]) -> Any:
    delta = SimpleNamespace(
        reasoning_content=None,
        content=None,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(usage=None, choices=[choice])


def _make_content_chunk(
    *,
    content: str | None = None,
    reasoning: str | None = None,
    finish_reason: str | None = None,
    usage: Any = None,
) -> Any:
    delta = SimpleNamespace(
        reasoning_content=reasoning,
        content=content,
        tool_calls=None,
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(
        id="supplier-response-safe-id",
        usage=usage,
        choices=[choice],
    )


@pytest.mark.asyncio
async def test_stream_records_only_safe_raw_response_diagnostics() -> None:
    model = CompatHarnessOpenAIChatModel(
        "dummy",
        api_key="sk-private-never-record",
        stream=True,
    )
    stream = FakeAsyncStream(
        [
            _make_content_chunk(reasoning="secret reasoning "),
            _make_content_chunk(content='{"answer":'),
            _make_content_chunk(content='"ok"}'),
            _make_content_chunk(
                finish_reason="stop",
                usage=SimpleNamespace(
                    prompt_tokens=11,
                    completion_tokens=7,
                    total_tokens=18,
                ),
            ),
        ],
    )

    with capture_openai_response_diagnostics():
        responses = await model.parse_stream_for_test(datetime.now(), stream)
    diagnostics = pop_openai_response_diagnostics(responses[-1])

    assert diagnostics.finish_reason == "stop"
    assert diagnostics.content_length == len('{"answer":"ok"}')
    assert diagnostics.reasoning_length == len("secret reasoning ")
    assert diagnostics.usage == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    rendered = repr(diagnostics)
    assert "secret reasoning" not in rendered
    assert "sk-private-never-record" not in rendered


@pytest.mark.asyncio
async def test_response_diagnostics_disabled_outside_openapi_adapter() -> None:
    model = CompatHarnessOpenAIChatModel(
        "dummy",
        api_key="sk-test",
        stream=True,
    )
    stream = FakeAsyncStream(
        [_make_content_chunk(content='{"answer":"ok"}')],
    )

    responses = await model.parse_stream_for_test(datetime.now(), stream)

    assert (
        pop_openai_response_diagnostics(
            responses[-1],
        ).content_length
        == 0
    )


async def test_stream_parser_skips_tool_call_without_function() -> None:
    model = CompatHarnessOpenAIChatModel(
        "dummy",
        api_key="sk-test",
        stream=True,
    )

    malformed_tool_call = SimpleNamespace(
        index=0,
        id="call_bad",
        function=None,
    )
    none_arguments_tool_call = SimpleNamespace(
        index=1,
        id="call_partial",
        function=SimpleNamespace(name="ping", arguments=None),
    )
    valid_tool_call = SimpleNamespace(
        index=0,
        id="call_ok",
        function=SimpleNamespace(name="ping", arguments='{"x":1}'),
    )

    stream = FakeAsyncStream(
        [
            _make_chunk([malformed_tool_call]),
            _make_chunk([none_arguments_tool_call]),
            _make_chunk([valid_tool_call]),
        ],
    )

    responses = await model.parse_stream_for_test(
        datetime.now(),
        stream,
    )

    assert responses
    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if block.get("type") == "tool_use"
    ]
    assert tool_blocks
    assert tool_blocks[-1]["name"] == "ping"
    assert tool_blocks[-1]["input"] == {"x": 1}


def test_sanitize_tool_call_normalizes_non_string_arguments() -> None:
    none_arguments_tool_call = SimpleNamespace(
        index=0,
        id="call_partial",
        function=SimpleNamespace(name="ping", arguments=None),
    )
    non_string_arguments_tool_call = SimpleNamespace(
        index=1,
        id="call_dict",
        function=SimpleNamespace(name="ping", arguments={"x": 2}),
    )
    missing_arguments_tool_call = SimpleNamespace(
        index=2,
        id="call_missing_args",
        function=SimpleNamespace(name="ping"),
    )
    missing_name_tool_call = SimpleNamespace(
        index=3,
        id="call_missing_name",
        function=SimpleNamespace(arguments={"x": 3}),
    )
    missing_name_and_arguments_tool_call = SimpleNamespace(
        index=4,
        id="call_missing_both",
        function=SimpleNamespace(),
    )

    sanitized_none_arguments = _sanitize_tool_call(none_arguments_tool_call)
    assert sanitized_none_arguments is not None
    assert sanitized_none_arguments.function.name == "ping"
    assert sanitized_none_arguments.function.arguments == ""

    sanitized_non_string_arguments = _sanitize_tool_call(
        non_string_arguments_tool_call,
    )
    assert sanitized_non_string_arguments is not None
    assert sanitized_non_string_arguments.function.name == "ping"
    assert isinstance(sanitized_non_string_arguments.function.arguments, str)
    assert json.loads(sanitized_non_string_arguments.function.arguments) == {
        "x": 2,
    }

    sanitized_missing_arguments = _sanitize_tool_call(
        missing_arguments_tool_call,
    )
    assert sanitized_missing_arguments is not None
    assert sanitized_missing_arguments.function.name == "ping"
    assert sanitized_missing_arguments.function.arguments == ""

    sanitized_missing_name = _sanitize_tool_call(missing_name_tool_call)
    assert sanitized_missing_name is not None
    assert sanitized_missing_name.function.name == ""
    assert isinstance(sanitized_missing_name.function.arguments, str)
    assert json.loads(sanitized_missing_name.function.arguments) == {"x": 3}

    sanitized_missing_name_and_arguments = _sanitize_tool_call(
        missing_name_and_arguments_tool_call,
    )
    assert sanitized_missing_name_and_arguments is not None
    assert sanitized_missing_name_and_arguments.function.name == ""
    assert sanitized_missing_name_and_arguments.function.arguments == ""


@pytest.mark.asyncio
async def test_not_given_overrides_persistent_json_format_for_tool_planning():
    model = CompatHarnessOpenAIChatModel(
        "dummy",
        api_key="sk-test",
        stream=False,
        generate_kwargs={"response_format": {"type": "json_object"}},
    )
    completions = _CapturingCompletions()
    model.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )

    with pytest.raises(_StopAfterCapture):
        await model(
            [{"role": "user", "content": "plan"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
            response_format=NOT_GIVEN,
        )

    assert completions.kwargs is not None
    assert completions.kwargs["response_format"] is NOT_GIVEN


@pytest.mark.asyncio
async def test_structured_tool_fallback_removes_persistent_response_format():
    model = CompatHarnessOpenAIChatModel(
        "dummy",
        api_key="sk-test",
        stream=False,
        generate_kwargs={"response_format": {"type": "json_object"}},
    )
    model._structured_output_fallback = True
    completions = _CapturingCompletions()
    model.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )

    with pytest.raises(_StopAfterCapture):
        await model(
            [{"role": "user", "content": "rewrite"}],
            structured_model=_InternalResult,
        )

    assert completions.kwargs is not None
    assert "response_format" not in completions.kwargs
    assert completions.kwargs["tools"][0]["function"]["name"]
