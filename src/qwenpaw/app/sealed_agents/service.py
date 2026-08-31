"""Installation and activation lifecycle for sealed agent releases."""

from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from .adapters import UnsupportedSealedRuntime, get_runtime_adapter
from .harness_protocol import HarnessProcess, HarnessProtocolError
from .models import RuntimeValidationRecord, SealedAgentRecord, SealedReleaseRecord
from .package import SealedPackageError, validate_sealed_package
from .registry import SealedAgentRegistry
from .runtime import PinnedSealedRuntime

logger = logging.getLogger(__name__)


class SealedAgentReleaseError(ValueError):
    """Sanitized release lifecycle failure."""


ReloadAgent = Callable[[str, Path], None]
RuntimeValidator = Callable[[PinnedSealedRuntime], Awaitable[RuntimeValidationRecord]]


class SealedAgentService:
    def __init__(
        self,
        *,
        root: Path,
        registry: SealedAgentRegistry,
        trusted_signers: Mapping[str, Ed25519PublicKey],
        reload_agent: ReloadAgent | None = None,
        runtime_validator: RuntimeValidator | None = None,
    ) -> None:
        self.root = Path(root)
        self.registry = registry
        self.trusted_signers = dict(trusted_signers)
        self._reload_agent = reload_agent or (lambda _agent_id, _path: None)
        self._runtime_validator = runtime_validator or self._validate_pinned_runtime

    def list_agents(self) -> list[SealedAgentRecord]:
        return self.registry.list_agents()

    def get_agent(self, agent_id: str) -> SealedAgentRecord | None:
        return self.registry.get_agent(agent_id)

    def release_root(self, agent_id: str, release_id: str) -> Path:
        return self.root / "releases" / agent_id / release_id

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

    def activate(self, agent_id: str, release_id: str) -> SealedAgentRecord:
        current = self._required_agent(agent_id)
        target = next(
            (item for item in current.releases if item.release_id == release_id),
            None,
        )
        if target is None:
            raise SealedAgentReleaseError("sealed agent release not found")
        if (
            target.runtime_adapter is not None
            and (
                target.runtime_validation is None
                or target.runtime_validation.status != "valid"
            )
        ):
            raise SealedAgentReleaseError("sealed agent runtime validation failed")
        agent_root = self.release_root(agent_id, release_id) / "agent"
        if not agent_root.is_dir():
            raise SealedAgentReleaseError("sealed agent release is unavailable")
        try:
            self._reload_agent(agent_id, agent_root)
        except Exception as exc:
            logger.error("Sealed agent activation failed for %s", agent_id)
            raise SealedAgentReleaseError("sealed agent activation failed") from exc

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
        adapter = target.runtime_adapter or "standard"
        contract_version = target.runtime_contract_version or "1"
        release_root = self.release_root(agent_id, release_id).resolve()
        entrypoint = target.entrypoint or "agent/agent.json"
        entrypoint_path = (release_root / entrypoint).resolve()
        if not entrypoint_path.is_relative_to(release_root):
            return self._persist_runtime_validation(
                current,
                release_id,
                RuntimeValidationRecord(
                    status="invalid",
                    adapter=adapter,
                    contract_version=contract_version,
                    error_code="unsafe_entrypoint",
                ),
            )
        pinned = PinnedSealedRuntime(
            agent_id=agent_id,
            release_id=release_id,
            version=target.version,
            content_digest=target.content_digest,
            release_root=release_root,
            entrypoint=entrypoint,
            adapter_key=(adapter, contract_version),
            failure_policy=target.runtime_failure_policy or "fail_closed",
        )
        try:
            validation = await self._runtime_validator(pinned)
        except (HarnessProtocolError, UnsupportedSealedRuntime):
            validation = RuntimeValidationRecord(
                status="invalid",
                adapter=adapter,
                contract_version=contract_version,
                error_code="runtime_validation_failed",
            )
        return self._persist_runtime_validation(current, release_id, validation)

    async def _validate_pinned_runtime(
        self,
        pinned: PinnedSealedRuntime,
    ) -> RuntimeValidationRecord:
        get_runtime_adapter(*pinned.adapter_key)
        if pinned.adapter_key == ("standard", "1"):
            return RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )
        async with HarnessProcess(pinned) as process:
            response = await process.invoke("handshake", {})
        payload = response.payload
        if (
            payload.get("adapter") != pinned.adapter_key[0]
            or payload.get("contract_version") != pinned.adapter_key[1]
        ):
            raise HarnessProtocolError("sealed harness handshake mismatch")
        return RuntimeValidationRecord(
            status="valid",
            adapter=pinned.adapter_key[0],
            contract_version=pinned.adapter_key[1],
        )

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
