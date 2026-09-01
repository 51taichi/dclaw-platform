from __future__ import annotations

import importlib
import json

from qwenpaw.app.sealed_agents.models import (
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.config.config import AgentProfileRef, Config


def _api():
    return importlib.import_module(
        "qwenpaw.app.sealed_agents.workspace_reconciliation",
    )


def _config_with_ordinary(workspace) -> Config:
    config = Config()
    config.agents.profiles["ordinary"] = AgentProfileRef(
        id="ordinary",
        workspace_dir=str(workspace),
        enabled=True,
    )
    return config


def _append_active_release(
    registry,
    sealed_root,
    agent_id,
    *,
    valid,
    enabled=True,
):
    release = SealedReleaseRecord(
        release_id=f"{agent_id}-release",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        state="active",
    )
    registry.upsert_agent(
        SealedAgentRecord(
            agent_id=agent_id,
            name=agent_id,
            enabled=enabled,
            active_release_id=release.release_id,
            releases=[release],
        ),
    )
    release_root = sealed_root / "releases" / agent_id / release.release_id
    agent_root = release_root / "agent"
    agent_root.mkdir(parents=True)
    if valid:
        (agent_root / "agent.json").write_text(
            json.dumps({"id": agent_id, "name": agent_id}),
            encoding="utf-8",
        )
    return release_root


def _active_release(tmp_path, agent_id="luyu"):
    sealed_root = tmp_path / "sealed"
    registry = SealedAgentRegistry(sealed_root)
    config = _config_with_ordinary(tmp_path / "ordinary")
    release_root = _append_active_release(
        registry,
        sealed_root,
        agent_id,
        valid=True,
    )
    return config, registry, sealed_root, release_root


def test_empty_registry_does_not_touch_ordinary_profiles(tmp_path):
    api = _api()
    config = _config_with_ordinary(tmp_path / "ordinary")
    before = config.model_dump(mode="json")
    result = api.reconcile_active_sealed_profiles(
        config,
        SealedAgentRegistry(tmp_path / "sealed"),
        tmp_path / "sealed",
    )
    assert result == api.WorkspaceReconciliationResult((), (), False)
    assert config.model_dump(mode="json") == before


def test_active_release_registers_exact_standard_workspace(tmp_path):
    api = _api()
    config, registry, sealed_root, release_root = _active_release(tmp_path)
    result = api.reconcile_active_sealed_profiles(
        config,
        registry,
        sealed_root,
    )
    assert result.reconciled == ("luyu",)
    assert result.unavailable == ()
    assert result.config_changed is True
    assert config.agents.profiles["luyu"] == AgentProfileRef(
        id="luyu",
        workspace_dir=str(release_root / "agent"),
        enabled=True,
    )
    validation = registry.get_agent("luyu").active_release.runtime_validation
    assert validation.status == "valid"
    assert validation.adapter == "standard"


def test_reconciliation_is_idempotent(tmp_path):
    api = _api()
    config, registry, sealed_root, _ = _active_release(tmp_path)
    first = api.reconcile_active_sealed_profiles(config, registry, sealed_root)
    validated_at = (
        registry.get_agent("luyu").active_release.runtime_validation.validated_at
    )
    second = api.reconcile_active_sealed_profiles(config, registry, sealed_root)
    assert first.config_changed is True
    assert second.config_changed is False
    assert (
        registry.get_agent("luyu").active_release.runtime_validation.validated_at
        == validated_at
    )


def test_one_invalid_agent_does_not_change_ordinary_or_valid_agent(tmp_path):
    api = _api()
    config, registry, sealed_root, _ = _active_release(tmp_path)
    broken_root = _append_active_release(
        registry,
        sealed_root,
        "broken",
        valid=False,
    )
    ordinary_before = config.agents.profiles["ordinary"].model_copy(deep=True)
    result = api.reconcile_active_sealed_profiles(config, registry, sealed_root)
    assert result.reconciled == ("luyu",)
    assert result.unavailable == ("broken",)
    assert config.agents.profiles["ordinary"] == ordinary_before
    assert config.agents.profiles["broken"] == AgentProfileRef(
        id="broken",
        workspace_dir=str(broken_root / "agent"),
        enabled=False,
    )
    validation = registry.get_agent("broken").active_release.runtime_validation
    assert validation.status == "invalid"
    assert validation.error_code == "agent_config_missing"


def test_disabled_sealed_agent_disables_existing_runtime_profile(tmp_path):
    api = _api()
    sealed_root = tmp_path / "sealed"
    registry = SealedAgentRegistry(sealed_root)
    config = _config_with_ordinary(tmp_path / "ordinary")
    release_root = _append_active_release(
        registry,
        sealed_root,
        "disabled",
        valid=True,
        enabled=False,
    )
    config.agents.profiles["disabled"] = AgentProfileRef(
        id="disabled",
        workspace_dir=str(release_root / "agent"),
        enabled=True,
    )
    result = api.reconcile_active_sealed_profiles(config, registry, sealed_root)
    assert result.reconciled == ()
    assert result.unavailable == ()
    assert result.config_changed is True
    assert config.agents.profiles["disabled"].enabled is False
