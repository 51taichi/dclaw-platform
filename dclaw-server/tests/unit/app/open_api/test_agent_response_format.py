# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import AsyncIterator
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from openai import NOT_GIVEN
from pydantic import BaseModel

from qwenpaw.app.open_api.agent_response_format import (
    OpenApiAgentExecutionError,
    OpenApiAgentResponseFormatModel,
    install_open_api_agent_response_format,
)
from qwenpaw.providers.openai_chat_model_compat import OpenAIChatModelCompat
from qwenpaw.providers.openai_response_diagnostics import (
    OpenAIResponseDiagnostics,
    stash_openai_response_diagnostics,
)


def _text(value: str) -> ChatResponse:
    return ChatResponse(
        content=[{"type": "text", "text": value}],
        is_last=True,
    )


def _tool(name: str, call_id: str = "call-1") -> ChatResponse:
    return ChatResponse(
        content=[
            {
                "type": "tool_use",
                "id": call_id,
                "name": name,
                "input": {"query": "customer"},
            },
        ],
        is_last=True,
    )


def _text_and_tool(name: str) -> ChatResponse:
    response = _tool(name)
    response.content = [
        {"type": "text", "text": "private planning draft"},
        *response.content,
    ]
    return response


class RecordingModel(ChatModelBase):
    def __init__(self, responses: list[ChatResponse | Exception]) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="deepseek-v4-flash",
            parameters=ChatModelBase.Parameters(),
            stream=True,
            context_size=32768,
        )
        self.model_name = self.model
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    @property
    def model_key(self) -> str:
        return "deepseek:deepseek-v4-flash"

    async def __call__(
        self,
        messages,
        tools=None,
        tool_choice=None,
        structured_model=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "structured_model": structured_model,
                **kwargs,
            },
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response

        async def stream() -> AsyncIterator[ChatResponse]:
            yield response

        return stream()


class StreamingRecordingModel(RecordingModel):
    def __init__(self, responses: list[list[ChatResponse]]) -> None:
        super().__init__([])
        self.stream_responses = list(responses)

    async def __call__(
        self,
        messages,
        tools=None,
        tool_choice=None,
        structured_model=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "structured_model": structured_model,
                **kwargs,
            },
        )
        chunks = self.stream_responses.pop(0)

        async def stream() -> AsyncIterator[ChatResponse]:
            for chunk in chunks:
                yield chunk

        return stream()


class PartialFailureModel(RecordingModel):
    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, **kwargs})

        async def stream() -> AsyncIterator[ChatResponse]:
            yield _text("partial supplier output")
            raise RuntimeError("private upstream response body")

        return stream()


async def _consume(result) -> list[ChatResponse]:
    return [item async for item in result]


@pytest.mark.asyncio
async def test_plain_reply_plans_without_format_then_finalizes_as_json():
    inner = RecordingModel(
        [
            _text("draft answer"),
            _text('{"answer":"final"}'),
        ],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    output = await _consume(
        await model(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
            tool_choice="auto",
        ),
    )

    assert output[-1].content == [
        {"type": "text", "text": '{"answer":"final"}'},
    ]
    assert inner.calls[0]["response_format"] is NOT_GIVEN
    assert inner.calls[0]["tools"]
    assert inner.calls[0]["tool_choice"] == "auto"
    assert inner.calls[1]["response_format"] == {"type": "json_object"}
    assert inner.calls[1]["tools"] is None
    assert inner.calls[1]["tool_choice"] is None
    assert "draft answer" in str(inner.calls[1]["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    [
        "search_knowledge",
        "mcp_customer_lookup",
        "excel_analyze_workbook",
    ],
)
async def test_each_tool_planning_turn_omits_response_format(tool_name):
    inner = RecordingModel(
        [
            _tool(tool_name),
            _text("draft after tool"),
            _text('{"answer":"done"}'),
        ],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )
    tools = [{"type": "function", "function": {"name": tool_name}}]

    first = await _consume(
        await model(
            [{"role": "user", "content": "use the tool"}],
            tools=tools,
        ),
    )
    second = await _consume(
        await model(
            [
                {"role": "user", "content": "use the tool"},
                {"role": "tool", "content": "tool result"},
            ],
            tools=tools,
        ),
    )

    assert first[-1].content[0]["type"] == "tool_use"
    assert second[-1].content[0]["text"] == '{"answer":"done"}'
    assert inner.calls[0]["response_format"] is NOT_GIVEN
    assert inner.calls[1]["response_format"] is NOT_GIVEN
    assert inner.calls[2]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_text_beside_tool_call_is_not_replayed_to_customer():
    inner = RecordingModel([_text_and_tool("search")])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    output = await _consume(
        await model(
            [{"role": "user", "content": "search"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
        ),
    )

    assert [block["type"] for block in output[-1].content] == ["tool_use"]
    assert "private planning draft" not in str(output[-1].content)


class RewriteResult(BaseModel):
    query: str


@pytest.mark.asyncio
async def test_internal_structured_call_uses_tool_fallback_without_format():
    inner = RecordingModel([_text("rewritten")])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    output = await _consume(
        await model(
            [{"role": "user", "content": "rewrite"}],
            structured_model=RewriteResult,
        ),
    )

    assert output[-1].content[0]["text"] == "rewritten"
    assert len(inner.calls) == 1
    assert inner.calls[0]["structured_model"] is RewriteResult
    assert inner.calls[0]["response_format"] is NOT_GIVEN


@pytest.mark.asyncio
async def test_internal_structured_stream_failure_is_model_failure():
    inner = PartialFailureModel([])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    result = await model(
        [{"role": "user", "content": "rewrite"}],
        structured_model=RewriteResult,
    )
    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await _consume(result)

    assert exc_info.value.code == "model_execution_failed"


def test_adapter_preserves_underlying_model_key():
    inner = RecordingModel([])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    assert model.model_key == "deepseek:deepseek-v4-flash"


class RecordingOpenAICompat(OpenAIChatModelCompat):
    def __init__(self) -> None:
        ChatModelBase.__init__(
            self,
            credential=CredentialBase(),
            model="deepseek-v4-flash",
            parameters=ChatModelBase.Parameters(),
            stream=True,
            context_size=32768,
        )
        self.model_name = self.model
        self.generate_kwargs = {
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        self._structured_output_fallback = False

    async def __call__(
        self, *args, **kwargs,
    ):  # pragma: no cover - installer only
        raise AssertionError("not called")


def test_installer_wraps_only_exact_json_object_openai_models():
    raw = RecordingOpenAICompat()
    agent = SimpleNamespace(model=raw)

    assert install_open_api_agent_response_format(agent) is True
    assert isinstance(agent.model, OpenApiAgentResponseFormatModel)
    assert agent.model.response_format == {"type": "json_object"}
    assert raw.generate_kwargs == {
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    assert raw._structured_output_fallback is True


def test_installer_finds_model_through_retry_and_meter_wrapper_shape():
    raw = RecordingOpenAICompat()
    metered = SimpleNamespace(_model=raw)
    retry = SimpleNamespace(
        _inner=metered,
        model_name=raw.model_name,
        stream=raw.stream,
    )
    agent = SimpleNamespace(model=retry)

    assert install_open_api_agent_response_format(agent) is True
    assert isinstance(agent.model, OpenApiAgentResponseFormatModel)
    assert agent.model._inner is retry


@pytest.mark.parametrize(
    "configured",
    [None, {"type": "json_schema"}, {"type": "json_object", "strict": True}],
)
def test_installer_leaves_non_exact_or_missing_format_unchanged(configured):
    raw = RecordingOpenAICompat()
    if configured is None:
        raw.generate_kwargs.pop("response_format")
    else:
        raw.generate_kwargs["response_format"] = configured
    agent = SimpleNamespace(model=raw)

    assert install_open_api_agent_response_format(agent) is False
    assert agent.model is raw


class UnsupportedConfiguredModel(ChatModelBase):
    def __init__(self) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="wrapped-deepseek",
            parameters=ChatModelBase.Parameters(),
            stream=True,
            context_size=32768,
        )
        self.model_name = self.model
        self.generate_kwargs = {
            "response_format": {"type": "json_object"},
        }

    async def __call__(self, *args, **kwargs):  # pragma: no cover - installer
        raise AssertionError("not called")


def test_configured_json_format_fails_closed_when_adapter_is_unavailable():
    raw = UnsupportedConfiguredModel()
    wrapped = SimpleNamespace(
        _inner=raw,
        model_name=raw.model_name,
        stream=raw.stream,
    )
    agent = SimpleNamespace(model=wrapped)

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        install_open_api_agent_response_format(agent)

    assert exc_info.value.code == "response_format_adapter_unavailable"
    assert "deepseek" not in exc_info.value.message.lower()
    assert agent.model is wrapped


@pytest.mark.asyncio
async def test_delta_stream_aggregates_all_text_and_drops_reasoning():
    inner = StreamingRecordingModel(
        [
            [
                ChatResponse(
                    content=[
                        {"type": "thinking", "thinking": "private "},
                        {"type": "text", "text": '{"answer":'},
                    ],
                    is_last=False,
                ),
                ChatResponse(
                    content=[
                        {"type": "thinking", "thinking": "reasoning"},
                        {"type": "text", "text": '"ok"}'},
                    ],
                    is_last=False,
                ),
                ChatResponse(content=[], is_last=True),
            ],
        ],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    output = await _consume(
        await model([{"role": "user", "content": "hello"}]),
    )

    assert output[-1].content == [
        {"type": "text", "text": '{"answer":"ok"}'},
    ]
    assert "private" not in str(output[-1].content)
    assert "reasoning" not in str(output[-1].content)


@pytest.mark.asyncio
async def test_cumulative_stream_is_not_duplicated_and_ignores_empty_tail():
    inner = StreamingRecordingModel(
        [
            [
                ChatResponse(
                    content=[
                        {"type": "thinking", "thinking": "secret"},
                        {"type": "text", "text": '{"answer":'},
                    ],
                    is_last=False,
                ),
                ChatResponse(
                    content=[
                        {"type": "thinking", "thinking": "secret plan"},
                        {"type": "text", "text": '{"answer":"ok"}'},
                    ],
                    is_last=False,
                ),
                ChatResponse(content=[], is_last=True),
            ],
        ],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    output = await _consume(
        await model([{"role": "user", "content": "hello"}]),
    )

    assert output[-1].content == [
        {"type": "text", "text": '{"answer":"ok"}'},
    ]


@pytest.mark.asyncio
async def test_reasoning_only_stream_fails_instead_of_leaking_reasoning():
    inner = StreamingRecordingModel(
        [
            [
                ChatResponse(
                    content=[
                        {"type": "thinking", "thinking": "private answer"},
                    ],
                    is_last=False,
                ),
                ChatResponse(content=[], is_last=True),
            ],
        ],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await model([{"role": "user", "content": "hello"}])

    assert exc_info.value.code == "empty_final_response"
    assert "private answer" not in exc_info.value.message


@pytest.mark.asyncio
async def test_final_supplier_diagnostics_are_logged_without_response_content(
    caplog,
):
    response = _text('{"private":"customer content"}')
    stash_openai_response_diagnostics(
        response,
        OpenAIResponseDiagnostics(
            finish_reason="stop",
            content_length=30,
            reasoning_length=14,
            usage={"prompt_tokens": 10, "completion_tokens": 4},
        ),
    )
    inner = RecordingModel([response])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    with caplog.at_level(
        logging.INFO,
        logger="qwenpaw.app.open_api.agent_response_format",
    ):
        await _consume(
            await model([{"role": "user", "content": "hello"}]),
        )

    rendered = "\n".join(record.message for record in caplog.records)
    assert "phase=final" in rendered
    assert "response_format_json_object=True" in rendered
    assert "finish_reason=stop" in rendered
    assert "content_length=30" in rendered
    assert "reasoning_length=14" in rendered
    assert "customer content" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "   "])
async def test_empty_final_response_is_an_explicit_failure(value):
    inner = RecordingModel([_text("draft"), _text(value)])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await model(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
        )

    assert exc_info.value.code == "empty_final_response"
    assert "private" not in exc_info.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["not json", "[]", "42", '"scalar"'])
async def test_non_object_final_response_is_an_explicit_failure(value):
    inner = RecordingModel([_text("draft"), _text(value)])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await model(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
        )

    assert exc_info.value.code == "invalid_final_response"


@pytest.mark.asyncio
async def test_empty_json_object_is_valid():
    inner = RecordingModel([_text("draft"), _text("{}")])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    output = await _consume(
        await model(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
        ),
    )

    assert output[-1].content[0]["text"] == "{}"


@pytest.mark.asyncio
async def test_supplier_failure_before_first_chunk_is_model_failure():
    inner = RecordingModel([RuntimeError("private supplier response")])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await model(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
        )

    assert exc_info.value.code == "model_execution_failed"
    assert "private supplier response" not in exc_info.value.message


@pytest.mark.asyncio
async def test_partial_supplier_failure_exposes_no_partial_answer():
    inner = PartialFailureModel([])
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await model(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
        )

    assert exc_info.value.code == "model_execution_failed"


@pytest.mark.asyncio
async def test_tool_error_can_recover_with_a_valid_final_response():
    inner = RecordingModel(
        [_tool("search"), _text("recovery draft"), _text('{"ok":true}')],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )
    tools = [{"type": "function", "function": {"name": "search"}}]
    await _consume(
        await model(
            [{"role": "user", "content": "search"}],
            tools=tools,
        ),
    )

    output = await _consume(
        await model(
            [
                {"role": "user", "content": "search"},
                {"role": "tool", "content": "Error: backend unavailable"},
            ],
            tools=tools,
        ),
    )

    assert output[-1].content[0]["text"] == '{"ok":true}'


@pytest.mark.asyncio
async def test_tool_error_without_valid_final_is_tool_execution_failure():
    inner = RecordingModel(
        [_tool("search"), _text("failed draft"), _text("")],
    )
    model = OpenApiAgentResponseFormatModel(
        inner,
        response_format={"type": "json_object"},
    )
    tools = [{"type": "function", "function": {"name": "search"}}]
    await _consume(
        await model(
            [{"role": "user", "content": "search"}],
            tools=tools,
        ),
    )

    with pytest.raises(OpenApiAgentExecutionError) as exc_info:
        await model(
            [
                {"role": "user", "content": "search"},
                {"role": "tool", "content": "Error: backend unavailable"},
            ],
            tools=tools,
        )

    assert exc_info.value.code == "tool_execution_failed"
