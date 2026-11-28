from __future__ import annotations

import pytest
from agentscope.message import (
    HintBlock,
    Msg as AgentScopeMsg,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolResultState,
)

from qwenpaw.agents.message_compat import Msg
from qwenpaw.app.runner.utils import agentscope_msg_to_message
from qwenpaw.runtime.contracts import (
    AgentRequest,
    ContentType,
    Message,
    MessageType,
    RunStatus,
    TextContent,
)
from qwenpaw.runtime.runner import Runner


def test_history_projection_hides_hint_blocks_from_public_messages():
    source = Msg(
        name="agent",
        role="assistant",
        content=[
            HintBlock(hint="<system-reminder>private runtime state</system-reminder>"),
            ThinkingBlock(id="thinking-1", thinking="checking"),
            TextBlock(id="text-1", text="public answer"),
        ],
        id="reply-1",
    )

    projected = agentscope_msg_to_message(source)

    assert [item.type for item in projected] == [
        MessageType.REASONING,
        MessageType.MESSAGE,
    ]
    public_text = "".join(
        content.text or ""
        for item in projected
        for content in item.content or []
        if content.type == ContentType.TEXT
    )
    assert public_text == "checkingpublic answer"
    assert "system-reminder" not in public_text
    assert all(item.status == RunStatus.Completed for item in projected)


def test_native_agentscope_message_projects_after_agent_loop_tool_call():
    source = AgentScopeMsg(
        name="agent",
        role="assistant",
        content=[TextBlock(text="任务已创建")],
        id="native-reply",
    )

    projected = agentscope_msg_to_message(source)

    assert len(projected) == 1
    assert projected[0].get_text_content() == "任务已创建"
    assert projected[0].status == RunStatus.Completed


class _TextStreamRunner(Runner):
    async def query_handler(self, **_kwargs):
        for text in ("Hel", "lo"):
            yield Msg(
                name="agent",
                role="assistant",
                content=[TextBlock(id="text-1", text=text)],
                id="reply-1",
                metadata={"stream_delta": True},
            )


@pytest.mark.asyncio
async def test_text_deltas_form_one_message_and_one_response_output():
    runner = _TextStreamRunner()
    await runner.start()
    try:
        events = [
            event
            async for event in runner.stream_query(
                AgentRequest(
                    input=[
                        Message(
                            role="user",
                            content=[TextContent(text="hello")],
                        ),
                    ],
                ),
            )
        ]
    finally:
        await runner.stop()

    message_events = [event for event in events if event.object == "message"]
    content_events = [event for event in events if event.object == "content"]
    delta_events = [event for event in content_events if event.delta]
    final_response = events[-1]

    assert {event.id for event in message_events} == {"reply-1"}
    assert [event.text for event in delta_events] == ["Hel", "lo"]
    assert {event.msg_id for event in content_events} == {"reply-1"}
    assert content_events[-1].text == "Hello"
    assert content_events[-1].status == RunStatus.Completed
    assert final_response.object == "response"
    assert final_response.status == RunStatus.Completed
    assert len(final_response.output) == 1
    assert final_response.output[0].get_text_content() == "Hello"


class _ToolOutputStreamRunner(Runner):
    async def query_handler(self, **_kwargs):
        for output in ("first ", "second"):
            yield Msg(
                name="agent",
                role="assistant",
                content=[
                    ToolResultBlock(
                        id="call-1",
                        name="example",
                        output=output,
                        state=ToolResultState.RUNNING,
                    ),
                ],
                id="reply-2",
                metadata={"stream_delta": True},
            )
        yield Msg(
            name="agent",
            role="assistant",
            content=[
                ToolResultBlock(
                    id="call-1",
                    name="example",
                    output="",
                    state=ToolResultState.SUCCESS,
                ),
            ],
            id="reply-2",
            metadata={"stream_terminal": True},
        )


@pytest.mark.asyncio
async def test_streamed_tool_output_keeps_accumulated_text_at_terminal():
    runner = _ToolOutputStreamRunner()
    await runner.start()
    try:
        events = [
            event
            async for event in runner.stream_query(
                AgentRequest(
                    input=[Message(role="user", content=[TextContent(text="go")])],
                ),
            )
        ]
    finally:
        await runner.stop()

    final_response = events[-1]
    assert len(final_response.output) == 1
    output = final_response.output[0]
    assert output.type == MessageType.PLUGIN_CALL_OUTPUT
    assert output.content[0].data["output"] == "first second"
    assert output.content[0].data["call_id"] == "call-1"


class _ReasoningAndTextStreamRunner(Runner):
    async def query_handler(self, **_kwargs):
        yield Msg(
            name="agent",
            role="assistant",
            content=[ThinkingBlock(id="thinking-1", thinking="considering")],
            id="reply-3",
            metadata={"stream_delta": True},
        )
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(id="text-1", text="answer")],
            id="reply-3",
            metadata={"stream_delta": True},
        )


@pytest.mark.asyncio
async def test_reasoning_and_text_streams_remain_distinct_and_complete():
    runner = _ReasoningAndTextStreamRunner()
    await runner.start()
    try:
        events = [
            event
            async for event in runner.stream_query(
                AgentRequest(
                    input=[Message(role="user", content=[TextContent(text="go")])],
                ),
            )
        ]
    finally:
        await runner.stop()

    final_response = events[-1]
    assert [item.type for item in final_response.output] == [
        MessageType.REASONING,
        MessageType.MESSAGE,
    ]
    assert [item.get_text_content() for item in final_response.output] == [
        "considering",
        "answer",
    ]
    assert len({item.id for item in final_response.output}) == 2
