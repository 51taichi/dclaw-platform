from __future__ import annotations

import pytest

from qwenpaw.app.open_api.agent_response_format import (
    is_trusted_direct_agent_open_api,
)


def test_direct_agent_open_api_requires_complete_server_identity():
    assert is_trusted_direct_agent_open_api(
        "open:app-1",
        {
            "target_type": "agent",
            "publication_id": "publication-1",
            "open_invocation_id": "invocation-1",
        },
    )


@pytest.mark.parametrize(
    ("channel", "metadata"),
    [
        (
            "console",
            {
                "target_type": "agent",
                "publication_id": "publication-1",
                "open_invocation_id": "invocation-1",
            },
        ),
        (
            "open:app-1",
            {
                "target_type": "expert_team",
                "publication_id": "publication-1",
                "open_invocation_id": "invocation-1",
            },
        ),
        (
            "open:app-1",
            {
                "target_type": "agent",
                "publication_id": "",
                "open_invocation_id": "invocation-1",
            },
        ),
        (
            "open:app-1",
            {
                "target_type": "agent",
                "publication_id": "publication-1",
            },
        ),
    ],
)
def test_non_direct_open_api_shapes_cannot_activate_policy(channel, metadata):
    assert not is_trusted_direct_agent_open_api(channel, metadata)
