# -*- coding: utf-8 -*-
from qwenpaw.exceptions import convert_model_exception
from qwenpaw.runtime.exceptions import (
    ModelExecutionException,
    ModelTimeoutException,
)


def test_incomplete_agentscope_stream_is_not_reported_as_timeout():
    error = RuntimeError(
        "Model returned an empty streaming response: no is_last=True chunk "
        "was received. Please increase the timeout if needed.",
    )

    converted = convert_model_exception(error, "deepseek-v4-flash-ga-260731")

    assert isinstance(converted, ModelExecutionException)
    assert not isinstance(converted, ModelTimeoutException)


def test_real_model_timeout_remains_a_timeout():
    converted = convert_model_exception(
        RuntimeError("Model inference timed out"),
        "model-a",
    )

    assert isinstance(converted, ModelTimeoutException)
