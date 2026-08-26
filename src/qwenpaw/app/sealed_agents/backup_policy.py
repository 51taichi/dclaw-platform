"""Backup boundaries: sealed releases are managed only by their installer."""

from __future__ import annotations

from ...backup.models import RestoreBackupRequest


class SealedBackupPolicyError(ValueError):
    pass


def filter_backup_agent_ids(
    agent_ids: list[str], *, sealed_ids: set[str]
) -> list[str]:
    return [agent_id for agent_id in agent_ids if agent_id not in sealed_ids]


def validate_restore_request(
    request: RestoreBackupRequest, *, sealed_ids: set[str]
) -> None:
    conflicts = sorted(set(request.agent_ids) & sealed_ids)
    if conflicts:
        raise SealedBackupPolicyError(
            "backup restore cannot overwrite sealed agents"
        )
    if sealed_ids and request.mode == "full" and request.include_global_config:
        raise SealedBackupPolicyError(
            "full global-config restore is unavailable while sealed agents exist"
        )
