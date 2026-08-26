import pytest

from qwenpaw.app.sealed_agents.backup_policy import (
    SealedBackupPolicyError,
    filter_backup_agent_ids,
    validate_restore_request,
)
from qwenpaw.backup.models import RestoreBackupRequest


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
