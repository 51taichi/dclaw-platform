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
