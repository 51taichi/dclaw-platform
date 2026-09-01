from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.sealed_agents.models import (
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.app.routers import open_api, open_api_admin


def _active_record():
    release = SealedReleaseRecord(
        release_id="release-1",
        version="2.1.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        state="active",
    )
    return SealedAgentRecord(
        agent_id="luyu",
        name="陆羽",
        active_release_id=release.release_id,
        releases=[release],
    )


def test_sealed_publication_policy_is_forced_server_side(monkeypatch):
    monkeypatch.setattr(
        open_api_admin,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(is_sealed=lambda agent_id: agent_id == "luyu"),
    )
    assert open_api_admin._target_publication_policy("agent", "luyu") == {
        "allowed_capability": "invoke_only",
        "response_policy": "sealed",
    }
    assert open_api_admin._target_publication_policy("agent", "ordinary") == {
        "allowed_capability": "standard",
        "response_policy": "standard",
    }


def test_disabled_or_unreleased_sealed_target_is_not_publishable(monkeypatch):
    record = SimpleNamespace(enabled=False, active_release_id=None)
    monkeypatch.setattr(
        open_api_admin,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda _agent_id: True,
            get_agent=lambda _agent_id: record,
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        open_api_admin._assert_target_exists("agent", "luyu")
    assert exc_info.value.status_code == 400
    assert "unavailable" in exc_info.value.detail.lower()


def test_ordinary_publication_never_reads_sealed_registry(monkeypatch):
    monkeypatch.setattr(
        open_api,
        "get_sealed_agent_registry",
        lambda: pytest.fail("ordinary publication read sealed Registry"),
    )
    publication = {
        "target_type": "agent",
        "target_id": "ordinary",
        "response_policy": "standard",
    }
    assert open_api._resolve_sealed_publication_release(publication) is None


def test_sealed_publication_resolves_active_release_for_audit(monkeypatch):
    record = _active_record()
    monkeypatch.setattr(
        open_api,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(get_agent=lambda _agent_id: record),
    )
    publication = {
        "target_type": "agent",
        "target_id": "luyu",
        "response_policy": "sealed",
    }
    assert open_api._resolve_sealed_publication_release(publication) == (
        record.active_release
    )
