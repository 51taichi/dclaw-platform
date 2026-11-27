from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.app.sealed_agents.models import SealedCapability
from qwenpaw.app.sealed_agents.policy import (
    assert_sealed_capability,
    deny_sealed_skill_asset_access,
)


@pytest.mark.parametrize(
    "capability",
    [SealedCapability.INVOKE, SealedCapability.PUBLIC_METADATA],
)
def test_public_capabilities_are_allowed(capability):
    assert_sealed_capability("luyu", capability, is_sealed=True)


@pytest.mark.parametrize(
    "capability",
    [
        SealedCapability.INSPECT,
        SealedCapability.EDIT,
        SealedCapability.CLONE,
        SealedCapability.EXPORT,
        SealedCapability.DOWNLOAD,
        SealedCapability.TRACE,
    ],
)
def test_protected_capabilities_are_denied_before_asset_access(capability):
    with pytest.raises(HTTPException) as exc_info:
        assert_sealed_capability("luyu", capability, is_sealed=True)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Sealed agent asset access denied"


def test_standard_agents_are_unchanged():
    assert_sealed_capability(
        "ordinary-agent",
        SealedCapability.DOWNLOAD,
        is_sealed=False,
    )


def test_global_workspace_skill_inventory_ignores_selected_sealed_agent(
    monkeypatch,
):
    class Registry:
        @staticmethod
        def is_sealed(agent_id):
            return agent_id == "luyu"

        @staticmethod
        def package_supports(agent_id, feature):
            return agent_id == "luyu" and feature == "mutable_skill_overlay"

    monkeypatch.setattr(
        "qwenpaw.app.sealed_agents.policy.get_sealed_agent_registry",
        lambda: Registry(),
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/user/skills/workspaces",
            "headers": [(b"x-agent-id", b"luyu")],
        },
    )

    deny_sealed_skill_asset_access(request)
