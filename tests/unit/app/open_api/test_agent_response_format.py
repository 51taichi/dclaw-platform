from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from openai import NOT_GIVEN
from pydantic import BaseModel

from qwenpaw.app.open_api.agent_response_format import (
    OpenApiAgentResponseFormatModel,
    install_open_api_agent_response_format,
)
from qwenpaw.providers.openai_chat_model_compat import OpenAIChatModelCompat


def _text(value: str) -> ChatResponse:
    return ChatResponse(content=[{"type": "text", "text": value}])


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
    )


class RecordingModel(ChatModelBase):
    def __init__(self, responses: list[ChatResponse | Exception]) -> None:
        super().__init__(model_name="deepseek-v4-flash", stream=True)
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

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


class RecordingOpenAICompat(OpenAIChatModelCompat):
    def __init__(self) -> None:
        ChatModelBase.__init__(
            self,
            model_name="deepseek-v4-flash",
            stream=True,
        )
        self.generate_kwargs = {
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        self._structured_output_fallback = False

    async def __call__(self, *args, **kwargs):  # pragma: no cover - installer only
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
