from __future__ import annotations

import json

from qwenpaw.app.sealed_agents.models import (
    AgentCapabilities,
    SealedAgentRecord,
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
