import json

import pytest
from agentscope.agent import Agent
from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from qwenpaw.agents.message_compat import Msg
from qwenpaw.agents.toolkit import DClawToolkit
from qwenpaw.app.runner.runner import _stream_printing_messages_interruptible


class _ScriptedModel(ChatModelBase):
    class Parameters(BaseModel):
        pass

    def __init__(self, responses, *, stream: bool) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="scripted",
            parameters=self.Parameters(),
            stream=stream,
        )
        self.formatter = OpenAIChatFormatter()
        self._responses = iter(responses)

    async def __call__(self, *_args, **_kwargs):
        response = next(self._responses)
        if isinstance(response, list):
            async def generate():
                for item in response:
                    yield item

            return generate()
        return response


@pytest.mark.asyncio
async def test_text_stream_emits_every_character_once_and_one_terminal():
    model = _ScriptedModel(
        [[
            ChatResponse(content=[TextBlock(text="Hel")], is_last=False),
            ChatResponse(content=[TextBlock(text="Hello")], is_last=True),
        ]],
        stream=True,
    )
    agent = Agent(name="agent", system_prompt="Reply.", model=model)

    chunks = [
        item
        async for item in _stream_printing_messages_interruptible(
            agents=[agent],
            inputs=[Msg("user", "hi", "user")],
        )
    ]

    assert "".join(msg.get_text_content() for msg, _ in chunks) == "Hello"
    assert [last for _, last in chunks] == [False, True]


@pytest.mark.asyncio
async def test_tool_stream_has_call_result_terminal_and_final_text():
    model = _ScriptedModel(
        [
            ChatResponse(
                content=[
                    ToolCallBlock(
                        id="call-1",
                        name="echo",
                        input=json.dumps({"value": "x"}),
                    ),
                ],
                is_last=True,
            ),
            ChatResponse(content=[TextBlock(text="done")], is_last=True),
        ],
        stream=False,
    )
    toolkit = DClawToolkit()

    async def echo(value: str) -> str:
        return f"echo:{value}"

    toolkit.register_tool_function(echo)
    agent = Agent(
        name="agent",
        system_prompt="Use the tool.",
        model=model,
        toolkit=toolkit,
    )

    chunks = [
        item
        async for item in _stream_printing_messages_interruptible(
            agents=[agent],
            inputs=[Msg("user", "go", "user")],
        )
    ]
    blocks = [block for msg, _ in chunks for block in msg.content]

    assert [block.type for block in blocks] == [
        "tool_call",
        "tool_result",
        "tool_result",
        "text",
    ]
    assert blocks[0].name == "echo"
    assert blocks[1].output == "echo:x"
    assert blocks[2].state == "success"
    assert chunks[-1][0].get_text_content() == "done"
    assert sum(last for _, last in chunks) == 1

