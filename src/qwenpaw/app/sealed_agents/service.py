"""Installation and activation lifecycle for sealed agent releases."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from .models import RuntimeValidationRecord, SealedAgentRecord, SealedReleaseRecord
from .package import SealedPackageError, validate_sealed_package
from .registry import SealedAgentRegistry
from .standard_workspace import (
    StandardWorkspaceError,
    validate_standard_workspace,
)
from .signing import SuperExpertTrustStore
from .runtime_workspace import ensure_runtime_workspace, runtime_workspace_root
from ..super_experts.capabilities import (
    CapabilityManifestError,
    validate_super_expert_manifest,
)
from ..super_experts.grants import (
    SuperExpertGrant,
    SuperExpertGrantPreview,
    SuperExpertGrantRepository,
)

class SealedAgentReleaseError(ValueError):
    """Sanitized release lifecycle failure."""


class SealedAgentService:
    def __init__(
        self,
        *,
        root: Path,
        registry: SealedAgentRegistry,
        trusted_signers: Mapping[str, Ed25519PublicKey],
        official_super_expert_signer_ids: frozenset[str] = frozenset(),
        grant_repository: SuperExpertGrantRepository | None = None,
    ) -> None:
        self.root = Path(root)
        self.registry = registry
        self.trusted_signers = dict(trusted_signers)
        self.super_expert_trust_store = SuperExpertTrustStore(
            official_signer_ids=official_super_expert_signer_ids,
        )
        self.grant_repository = grant_repository or SuperExpertGrantRepository(
            self.root,
        )

    def list_agents(self) -> list[SealedAgentRecord]:
        return self.registry.list_agents()

    def get_agent(self, agent_id: str) -> SealedAgentRecord | None:
        return self.registry.get_agent(agent_id)

    def release_root(self, agent_id: str, release_id: str) -> Path:
        return self.root / "releases" / agent_id / release_id

    def runtime_workspace_root(self, agent_id: str, release_id: str) -> Path:
        return runtime_workspace_root(self.root, agent_id, release_id)

    def prepare_runtime_workspace(self, agent_id: str, release_id: str) -> Path:
        return ensure_runtime_workspace(self.root, agent_id, release_id)

    def install(self, data: bytes) -> SealedReleaseRecord:
        try:
            validated = validate_sealed_package(
                data,
                trusted_signers=self.trusted_signers,
                staging_root=self.root / "staging",
            )
        except SealedPackageError as exc:
            raise SealedAgentReleaseError(str(exc)) from exc

        manifest = validated.manifest
        if manifest.package_type == "super_expert":
            try:
                validate_super_expert_manifest(
                    manifest,
                    self.super_expert_trust_store,
                )
            except CapabilityManifestError as exc:
                shutil.rmtree(validated.extracted_root, ignore_errors=True)
                raise SealedAgentReleaseError(str(exc)) from exc
        current = self.registry.get_agent(manifest.agent_id)
        try:
            incoming_version = Version(manifest.version)
            existing_versions = [
                Version(release.version)
                for release in (current.releases if current else [])
            ]
        except InvalidVersion as exc:
            shutil.rmtree(validated.extracted_root, ignore_errors=True)
            raise SealedAgentReleaseError("invalid sealed agent version") from exc
        if incoming_version in existing_versions:
            shutil.rmtree(validated.extracted_root, ignore_errors=True)
            raise SealedAgentReleaseError("sealed agent version already exists")
        if existing_versions and incoming_version < max(existing_versions):
            shutil.rmtree(validated.extracted_root, ignore_errors=True)
            raise SealedAgentReleaseError("sealed agent version downgrade is denied")

        release = SealedReleaseRecord(
            release_id=uuid.uuid4().hex,
            version=manifest.version,
            content_digest=manifest.content_digest,
            signer_id=manifest.signer_id,
            package_type=manifest.package_type,
            capability_digest=manifest.capability_digest,
            declared_capabilities=tuple(
                (item.capability_id, item.contract_version)
                for item in manifest.capabilities
            ),
            orchestration_capability_id=(
                manifest.orchestration.capability_id
                if manifest.orchestration
                else None
            ),
            orchestration_contract_version=(
                manifest.orchestration.contract_version
                if manifest.orchestration
                else None
            ),
            orchestration_entrypoint=(
                manifest.orchestration.entrypoint
                if manifest.orchestration
                else None
            ),
            orchestration_required_host_capabilities=(
                manifest.orchestration.required_host_capabilities
                if manifest.orchestration
                else ()
            ),
            entrypoint=manifest.entrypoint,
            runtime_adapter=(manifest.runtime.adapter if manifest.runtime else None),
            runtime_contract_version=(
                manifest.runtime.contract_version if manifest.runtime else None
            ),
            runtime_failure_policy=(
                manifest.runtime.failure_policy if manifest.runtime else None
            ),
            state="ready",
        )
        destination = self.release_root(manifest.agent_id, release.release_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(validated.extracted_root), str(destination))
            record = SealedAgentRecord(
                agent_id=manifest.agent_id,
                name=manifest.name,
                description=manifest.public_metadata.description,
                icon=manifest.public_metadata.icon,
                enabled=current.enabled if current else True,
                active_release_id=current.active_release_id if current else None,
                releases=[*(current.releases if current else []), release],
            )
            self.registry.upsert_agent(record)
        except Exception as exc:
            shutil.rmtree(destination, ignore_errors=True)
            raise SealedAgentReleaseError("sealed agent installation failed") from exc
        return release

    def preview_grant(
        self,
        agent_id: str,
        release_id: str,
        *,
        tenant_id: str,
    ) -> SuperExpertGrantPreview:
        release = self._required_release(agent_id, release_id)
        return self.grant_repository.preview(
            agent_id,
            release,
            tenant_id=tenant_id,
        )

    def grant_installation(
        self,
        agent_id: str,
        release_id: str,
        *,
        tenant_id: str,
        administrator_id: str,
    ) -> SuperExpertGrant:
        preview = self.preview_grant(
            agent_id,
            release_id,
            tenant_id=tenant_id,
        )
        return self.grant_repository.grant_installation(
            preview,
            administrator_id=administrator_id,
        )

    def cancel_grant_preview(
        self,
        agent_id: str,
        release_id: str,
        *,
        tenant_id: str,
    ) -> None:
        self.grant_repository.cancel(
            self.preview_grant(agent_id, release_id, tenant_id=tenant_id),
        )

    def activate(
        self,
        agent_id: str,
        release_id: str,
        *,
        tenant_id: str = "local",
    ) -> SealedAgentRecord:
        current = self._required_agent(agent_id)
        target = next(
            (item for item in current.releases if item.release_id == release_id),
            None,
        )
        if target is None:
            raise SealedAgentReleaseError("sealed agent release not found")
        if target.package_type == "super_expert" and not (
            self.grant_repository.is_release_granted(
                agent_id,
                target,
                tenant_id=tenant_id,
            )
        ):
            raise SealedAgentReleaseError(
                "super expert installation authorization is required",
            )
        if (
            target.runtime_validation is None
            or target.runtime_validation.status != "valid"
            or target.runtime_validation.adapter != "standard"
        ):
            raise SealedAgentReleaseError("sealed agent runtime validation failed")
        agent_root = self.release_root(agent_id, release_id) / "agent"
        try:
            validate_standard_workspace(agent_id, agent_root)
        except StandardWorkspaceError as exc:
            raise SealedAgentReleaseError("sealed agent release is unavailable")

        releases: list[SealedReleaseRecord] = []
        for item in current.releases:
            state = item.state
            if item.release_id == release_id:
                state = "active"
            elif item.release_id == current.active_release_id and state == "active":
                state = "superseded"
            releases.append(item.model_copy(update={"state": state}))
        updated = current.model_copy(
            update={
                "active_release_id": release_id,
                "enabled": True,
                "releases": releases,
            },
        )
        return self.registry.upsert_agent(updated)

    async def validate_release_runtime(
        self,
        agent_id: str,
        release_id: str,
    ) -> RuntimeValidationRecord:
        current = self._required_agent(agent_id)
        target = next(
            (item for item in current.releases if item.release_id == release_id),
            None,
        )
        if target is None:
            raise SealedAgentReleaseError("sealed agent release not found")
        try:
            validate_standard_workspace(
                agent_id,
                self.release_root(agent_id, release_id) / "agent",
            )
        except StandardWorkspaceError as exc:
            validation = RuntimeValidationRecord(
                status="invalid",
                adapter="standard",
                contract_version="1",
                error_code=exc.error_code,
            )
        else:
            validation = RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )
        return self._persist_runtime_validation(current, release_id, validation)

    def _persist_runtime_validation(
        self,
        current: SealedAgentRecord,
        release_id: str,
        validation: RuntimeValidationRecord,
    ) -> RuntimeValidationRecord:
        releases = [
            item.model_copy(update={"runtime_validation": validation})
            if item.release_id == release_id
            else item
            for item in current.releases
        ]
        self.registry.upsert_agent(current.model_copy(update={"releases": releases}))
        return validation

    def disable(self, agent_id: str) -> SealedAgentRecord:
        current = self._required_agent(agent_id)
        return self.registry.upsert_agent(
            current.model_copy(update={"enabled": False}),
        )

    def enable(self, agent_id: str) -> SealedAgentRecord:
        current = self._required_agent(agent_id)
        if current.active_release_id is None:
            raise SealedAgentReleaseError("sealed agent has no active release")
        return self.registry.upsert_agent(
            current.model_copy(update={"enabled": True}),
        )

    def _required_agent(self, agent_id: str) -> SealedAgentRecord:
        current = self.registry.get_agent(agent_id)
        if current is None:
            raise SealedAgentReleaseError("sealed agent not found")
        return current

    def _required_release(
        self,
        agent_id: str,
        release_id: str,
    ) -> SealedReleaseRecord:
        current = self._required_agent(agent_id)
        release = next(
            (item for item in current.releases if item.release_id == release_id),
            None,
        )
        if release is None:
            raise SealedAgentReleaseError("sealed agent release not found")
        return release
