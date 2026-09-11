import pytest
from types import SimpleNamespace
from openai import NOT_GIVEN
from qwenpaw.app.workspace.public_stream import public_text_model


@pytest.mark.asyncio
async def test_public_text_override_is_local_and_keeps_tools():
    calls = []

    class Model:
        generate_kwargs = {
            "response_format": {"type": "json_object"},
            "max_tokens": 4096,
        }

        async def __call__(self, *args, **kwargs):
            calls.append(kwargs)

    inner = Model()

    class Wrapper:
        _inner = inner

        async def __call__(self, *args, **kwargs):
            return await self._inner(*args, **kwargs)

    class Meter:
        _model = Wrapper()

        async def __call__(self, *args, **kwargs):
            return await self._model(*args, **kwargs)

    wrapped = public_text_model(Meter())
    await wrapped([], tools=["skill"])
    assert calls[0]["response_format"] is NOT_GIVEN
    assert calls[0]["tools"] == ["skill"]
    assert inner.generate_kwargs["response_format"] == {"type": "json_object"}
    schema = {"type": "json_schema", "json_schema": {"name": "result"}}
    await wrapped([], response_format=schema)
    assert calls[1]["response_format"] is schema


def test_non_json_defaults_are_untouched():
    m = SimpleNamespace(generate_kwargs={"max_tokens": 4096})
    assert public_text_model(m) is m

@pytest.mark.asyncio
async def test_original_model_is_restored_after_agent_failure():
    from qwenpaw.app.workspace.public_stream import execute_public_agent

    original = SimpleNamespace(generate_kwargs={"response_format": {"type": "json_object"}})

    class Agent:
        model = original
        msg_queue = None
        _disable_msg_queue = True

        def set_msg_queue_enabled(self, enabled, queue=None):
            self.msg_queue = queue if enabled else None
            self._disable_msg_queue = not enabled

        async def __call__(self, messages):
            assert self.model is not original
            raise RuntimeError("provider unavailable")

    async def receive(message):
        raise AssertionError("no public output")

    agent = Agent()
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await execute_public_agent(agent, [], receive)
    assert agent.model is original
    assert agent.msg_queue is None and agent._disable_msg_queue
