"""Reconcile active sealed releases into ordinary Agent profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...config.config import AgentProfileRef, Config
from .models import (
    RuntimeValidationRecord,
    SealedAgentRecord,
    SealedReleaseRecord,
)
from .registry import SealedAgentRegistry
from .standard_workspace import (
    StandardWorkspaceError,
    validate_standard_workspace,
)


@dataclass(frozen=True)
class WorkspaceReconciliationResult:
    reconciled: tuple[str, ...]
    unavailable: tuple[str, ...]
    config_changed: bool


def _validation_matches(
    current: RuntimeValidationRecord | None,
    *,
    status: str,
    error_code: str | None,
) -> bool:
    return bool(
        current is not None
        and current.status == status
        and current.adapter == "standard"
        and current.contract_version == "1"
        and current.error_code == error_code
    )


def _persist_standard_validation(
    registry: SealedAgentRegistry,
    record: SealedAgentRecord,
    active: SealedReleaseRecord,
    error_code: str | None,
) -> None:
    status = "invalid" if error_code else "valid"
    if _validation_matches(
        active.runtime_validation,
        status=status,
        error_code=error_code,
    ):
        return
    validation = RuntimeValidationRecord(
        status=status,
        adapter="standard",
        contract_version="1",
        error_code=error_code,
    )
    releases = [
        release.model_copy(update={"runtime_validation": validation})
        if release.release_id == active.release_id
        else release
        for release in record.releases
    ]
    registry.upsert_agent(record.model_copy(update={"releases": releases}))


def _profile_for_workspace(
    previous: AgentProfileRef | None,
    *,
    agent_id: str,
    workspace_root: Path,
    enabled: bool,
) -> AgentProfileRef:
    updates = {
        "id": agent_id,
        "workspace_dir": str(workspace_root),
        "enabled": enabled,
    }
    if previous is not None:
        return previous.model_copy(update=updates)
    return AgentProfileRef(**updates)


def reconcile_active_sealed_profiles(
    config: Config,
    registry: SealedAgentRegistry,
    sealed_root: Path,
) -> WorkspaceReconciliationResult:
    """Align sealed Registry state with ordinary Agent profile bindings."""

    reconciled: list[str] = []
    unavailable: list[str] = []
    changed = False
    for record in sorted(
        registry.list_agents(),
        key=lambda item: item.agent_id,
    ):
        active = record.active_release
        previous = config.agents.profiles.get(record.agent_id)
        if not record.enabled or active is None:
            if previous is not None and previous.enabled:
                config.agents.profiles[record.agent_id] = previous.model_copy(
                    update={"enabled": False},
                )
                changed = True
            continue

        workspace_root = (
            Path(sealed_root)
            / "releases"
            / record.agent_id
            / active.release_id
            / "agent"
        )
        try:
            validate_standard_workspace(record.agent_id, workspace_root)
        except StandardWorkspaceError as exc:
            unavailable.append(record.agent_id)
            desired = _profile_for_workspace(
                previous,
                agent_id=record.agent_id,
                workspace_root=workspace_root,
                enabled=False,
            )
            if previous != desired:
                config.agents.profiles[record.agent_id] = desired
                changed = True
            _persist_standard_validation(
                registry,
                record,
                active,
                exc.error_code,
            )
            continue

        desired = _profile_for_workspace(
            previous,
            agent_id=record.agent_id,
            workspace_root=workspace_root,
            enabled=True,
        )
        if previous != desired:
            config.agents.profiles[record.agent_id] = desired
            changed = True
        reconciled.append(record.agent_id)
        _persist_standard_validation(registry, record, active, None)

    return WorkspaceReconciliationResult(
        reconciled=tuple(reconciled),
        unavailable=tuple(unavailable),
        config_changed=changed,
    )
