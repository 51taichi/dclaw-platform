"""Plugin-owned lifecycle for signed ``super_expert`` packages."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .capabilities import validate_super_expert_manifest
from .grants import SuperExpertGrantRepository
from .trust import SuperExpertTrustStore
from .release_retention import retain_releases


class SuperAgentPackageHandler:
    """Validate, authorize and grant one Super Agent package type."""

    package_type = "super_expert"
    requires_installation_grant = True
    runtime_features = frozenset(
        {
            "extended_output",
            "harness_status",
            "mcp_client",
            "mutable_skill_overlay",
            "unrestricted_tools",
        },
    )

    def __init__(
        self,
        root: Path,
        *,
        official_signer_ids: frozenset[str],
        trusted_signers: Mapping[str, Any] | None = None,
        grant_repository: SuperExpertGrantRepository | None = None,
    ) -> None:
        self.trust_store = SuperExpertTrustStore(
            official_signer_ids=official_signer_ids,
        )
        self._trusted_signers = dict(trusted_signers or {})
        self.grant_repository = grant_repository or SuperExpertGrantRepository(
            root,
        )

    def validate_manifest(self, manifest) -> None:
        validate_super_expert_manifest(manifest, self.trust_store)

    @property
    def trusted_signers(self) -> Mapping[str, Any]:
        return self._trusted_signers

    def is_signer_authorized(self, signer_id: str) -> bool:
        return self.trust_store.is_official(signer_id)

    def supports_runtime_feature(self, feature: str) -> bool:
        return feature in self.runtime_features

    def on_release_committed(
        self, service: Any, agent_id: str, release_id: str,
    ) -> None:
        retain_releases(service, agent_id, release_id)

    def preview_grant(self, agent_id, release, *, tenant_id: str):
        return self.grant_repository.preview(
            agent_id,
            release,
            tenant_id=tenant_id,
        )

    def grant_installation(
        self,
        agent_id,
        release,
        *,
        tenant_id: str,
        administrator_id: str,
    ):
        preview = self.preview_grant(agent_id, release, tenant_id=tenant_id)
        return self.grant_repository.grant_installation(
            preview,
            administrator_id=administrator_id,
        )

    def cancel_grant(self, agent_id, release, *, tenant_id: str) -> None:
        self.grant_repository.cancel(
            self.preview_grant(agent_id, release, tenant_id=tenant_id),
        )

    def is_release_granted(self, agent_id, release, *, tenant_id: str) -> bool:
        return self.grant_repository.is_release_granted(
            agent_id,
            release,
            tenant_id=tenant_id,
        )


class PublicSuperAgentPackageHandler(SuperAgentPackageHandler):
    """Self-service type with bounded platform tools and developer signers."""

    package_type = "super_expert_public"
    runtime_features = frozenset({"extended_output", "harness_status"})

    def __init__(
        self,
        root: Path,
        *,
        publisher_repository: Any,
        grant_repository: SuperExpertGrantRepository | None = None,
    ) -> None:
        super().__init__(
            root,
            official_signer_ids=frozenset(),
            grant_repository=grant_repository,
        )
        self.publisher_repository = publisher_repository

    @property
    def trusted_signers(self) -> Mapping[str, Any]:
        return self.publisher_repository.trusted_signers()

    def validate_manifest(self, manifest) -> None:
        validate_super_expert_manifest(
            manifest,
            SuperExpertTrustStore(
                official_signer_ids=frozenset(),
                developer_signer_ids=frozenset(self.trusted_signers),
            ),
            expected_package_type=self.package_type,
        )

    def is_signer_authorized(self, signer_id: str) -> bool:
        return self.publisher_repository.signer_owner(signer_id) is not None


__all__ = ["SuperAgentPackageHandler", "PublicSuperAgentPackageHandler"]
