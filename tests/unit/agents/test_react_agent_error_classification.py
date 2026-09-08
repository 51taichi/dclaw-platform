from __future__ import annotations

from qwenpaw.agents.react_agent import QwenPawAgent


class _BadRequest(RuntimeError):
    status_code = 400


def test_json_response_format_error_is_not_classified_as_media() -> None:
    error = _BadRequest(
        "Prompt must contain the word 'json' to use response_format "
        "of type json_object",
    )

    assert QwenPawAgent._is_bad_request_or_media_error(error) is False


def test_media_validation_error_is_classified_as_media() -> None:
    error = _BadRequest("Unsupported image_url content for this model")

    assert QwenPawAgent._is_bad_request_or_media_error(error) is True
