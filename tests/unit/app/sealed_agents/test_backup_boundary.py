import pytest
import json
import zipfile

from qwenpaw.app.sealed_agents.backup_policy import (
    SealedBackupPolicyError,
    filter_backup_agent_ids,
    validate_restore_request,
)
from qwenpaw.backup.models import RestoreBackupRequest
from qwenpaw.backup._ops import create_helpers


def test_backup_selection_silently_excludes_sealed_agents():
    assert filter_backup_agent_ids(
        ["writer", "luyu", "analyst"], sealed_ids={"luyu"}
    ) == ["writer", "analyst"]


def test_restore_cannot_target_sealed_agent():
    request = RestoreBackupRequest(agent_ids=["luyu"])
    with pytest.raises(SealedBackupPolicyError):
        validate_restore_request(request, sealed_ids={"luyu"})


def test_full_global_restore_is_blocked_while_sealed_agents_exist():
    request = RestoreBackupRequest(
        mode="full", include_global_config=True, include_agents=False
    )
    with pytest.raises(SealedBackupPolicyError):
        validate_restore_request(request, sealed_ids={"luyu"})


def test_custom_restore_of_standard_agents_remains_available():
    request = RestoreBackupRequest(mode="custom", agent_ids=["writer"])
    validate_restore_request(request, sealed_ids={"luyu"})


def test_global_config_backup_removes_sealed_profile_and_private_path(
    monkeypatch, tmp_path
):
    config = {
        "agents": {
            "profiles": {
                "writer": {"id": "writer", "workspace_dir": "/public/writer"},
                "luyu": {"id": "luyu", "workspace_dir": "/private/release"},
            },
            "agent_order": ["writer", "luyu"],
        }
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    registry = type(
        "Registry",
        (),
        {"list_agents": lambda self: [type("R", (), {"agent_id": "luyu"})()]},
    )()
    monkeypatch.setattr(create_helpers, "WORKING_DIR", tmp_path)
    from qwenpaw.app.sealed_agents import registry as registry_module

    monkeypatch.setattr(registry_module, "get_sealed_agent_registry", lambda: registry)
    archive_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        create_helpers.add_global_config(archive)
    with zipfile.ZipFile(archive_path) as archive:
        backed_up = json.loads(archive.read("data/config.json"))

    assert set(backed_up["agents"]["profiles"]) == {"writer"}
    assert backed_up["agents"]["agent_order"] == ["writer"]
    assert "/private/release" not in json.dumps(backed_up)
