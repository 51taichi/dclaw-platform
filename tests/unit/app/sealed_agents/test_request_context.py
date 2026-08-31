from __future__ import annotations

import pytest

from qwenpaw.app.sealed_agents.request_context import (
    SealedAdapterRequest,
    SealedRequestMetadataError,
    normalize_untrusted_metadata,
)


def test_nested_open_api_metadata_is_deep_copied():
    source = {"luyu_debug": True, "case": {"id": "case-1"}}

    normalized = normalize_untrusted_metadata(source)
    source["case"]["id"] = "changed"

    assert normalized == {"luyu_debug": True, "case": {"id": "case-1"}}


def test_metadata_cannot_override_trusted_identity():
    request = SealedAdapterRequest(
        messages=(),
        trusted_context={"agent_id": "trusted", "release_id": "release-1"},
        metadata={"agent_id": "attacker", "release_id": "attacker-release"},
    )

    assert request.trusted_context["agent_id"] == "trusted"
    assert request.metadata["agent_id"] == "attacker"


@pytest.mark.parametrize("value", ["not-an-object", ["not-an-object"]])
def test_metadata_must_be_an_object(value):
    with pytest.raises(SealedRequestMetadataError, match="object"):
        normalize_untrusted_metadata(value)


def test_metadata_depth_is_bounded():
    value = {}
    cursor = value
    for _ in range(18):
        cursor["nested"] = {}
        cursor = cursor["nested"]

    with pytest.raises(SealedRequestMetadataError, match="deeply nested"):
        normalize_untrusted_metadata(value)


def test_metadata_size_is_bounded():
    with pytest.raises(SealedRequestMetadataError, match="too large"):
        normalize_untrusted_metadata({"value": "x" * (64 * 1024)})
