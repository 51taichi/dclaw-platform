from __future__ import annotations

import json

from qwenpaw.app.sealed_agents.models import (
    AgentCapabilities,
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry


def _agent(agent_id: str, *, name: str | None = None) -> SealedAgentRecord:
    return SealedAgentRecord(
        agent_id=agent_id,
        name=name or agent_id,
        description=f"{agent_id} description",
        enabled=True,
        active_release_id=None,
    )


def test_missing_registry_behaves_as_empty(tmp_path):
    registry = SealedAgentRegistry(tmp_path)

    assert registry.list_agents() == []
    assert registry.get_agent("luyu") is None


def test_registry_persists_multiple_agents_atomically(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(_agent("luyu", name="陆羽"))
    registry.upsert_agent(_agent("tea-master"))

    reloaded = SealedAgentRegistry(tmp_path)

    assert [item.agent_id for item in reloaded.list_agents()] == [
        "luyu",
        "tea-master",
    ]
    assert reloaded.get_agent("luyu").name == "陆羽"
    assert not (tmp_path / "registry.json.tmp").exists()


def test_corrupt_registry_is_isolated_as_empty(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "registry.json").write_text("{not-json", encoding="utf-8")

    registry = SealedAgentRegistry(tmp_path)

    assert registry.list_agents() == []


def test_registry_rejects_non_sealed_records(tmp_path):
    payload = _agent("luyu").model_dump(mode="json")
    payload["agent_type"] = "standard"
    (tmp_path / "registry.json").write_text(
        json.dumps({"schema_version": 1, "agents": [payload]}),
        encoding="utf-8",
    )

    assert SealedAgentRegistry(tmp_path).list_agents() == []


def test_registry_classifies_only_active_super_expert_release(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    release = SealedReleaseRecord(
        release_id="release-1",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        package_type="super_expert",
        state="active",
    )
    registry.upsert_agent(
        SealedAgentRecord(
            agent_id="luyu",
            name="陆羽",
            active_release_id=release.release_id,
            releases=[release],
        ),
    )

    assert registry.is_super_expert("luyu")
    assert not registry.is_super_expert("missing")


def test_registry_classifies_package_type_from_pinned_workspace(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    super_release = SealedReleaseRecord(
        release_id="super-release",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        package_type="super_expert",
        state="superseded",
    )
    sealed_release = super_release.model_copy(
        update={
            "release_id": "sealed-release",
            "package_type": "sealed_agent",
            "state": "active",
        },
    )
    registry.upsert_agent(
        SealedAgentRecord(
            agent_id="luyu",
            name="陆羽",
            active_release_id=sealed_release.release_id,
            releases=[super_release, sealed_release],
        ),
    )

    super_workspace = (
        tmp_path / "runtime_workspaces" / "luyu" / "super-release" / "agent"
    )
    sealed_workspace = (
        tmp_path / "runtime_workspaces" / "luyu" / "sealed-release" / "agent"
    )

    assert not registry.is_super_expert_workspace("luyu", super_workspace)
    assert not registry.is_super_expert_workspace("luyu", sealed_workspace)
    assert not registry.is_super_expert_workspace(
        "luyu",
        tmp_path / "unknown-release" / "agent",
    )


def test_sealed_capabilities_are_invoke_only():
    capabilities = AgentCapabilities.for_sealed_global()

    assert capabilities.model_dump() == {
        "invoke": True,
        "public_metadata": True,
        "inspect": False,
        "edit": False,
        "clone": False,
        "export": False,
        "download": False,
        "trace": False,
    }
