"""All-or-nothing installation grants for signed super-expert packages."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qwenpaw.app.sealed_agents.models import SealedReleaseRecord
from .capabilities import get_platform_capability_catalog


class SuperExpertGrantError(ValueError):
    """A public-safe grant validation failure."""


class SuperExpertGrantPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_id: str
    tenant_id: str
    agent_id: str
    release_id: str
    package_digest: str
    package_version: str
    capability_digest: str
    capabilities: tuple[tuple[str, str], ...]


class SuperExpertGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installation_id: str
    tenant_id: str
    agent_id: str
    release_id: str
    package_digest: str
    package_version: str
    capability_digest: str
    capabilities: tuple[tuple[str, str], ...]
    administrator_id: str
    authorization_source: Literal["administrator", "publisher"] = "administrator"
    granted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    installation_id: str
    capability_id: str
    contract_version: str
    reason: str


class _GrantDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    grants: list[SuperExpertGrant] = Field(default_factory=list)


class SuperExpertGrantRepository:
    """Atomic local store whose grant always equals one signed manifest set."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "super_expert_grants.json"
        self._lock = threading.RLock()

    def preview(
        self,
        agent_id: str,
        release: SealedReleaseRecord,
        *,
        tenant_id: str,
    ) -> SuperExpertGrantPreview:
        if release.package_type not in {"super_expert", "super_expert_public"}:
            raise SuperExpertGrantError(
                "release is not a super expert package",
            )
        if not release.capability_digest or not release.declared_capabilities:
            raise SuperExpertGrantError(
                "super expert capability declaration is missing",
            )
        catalog = get_platform_capability_catalog()
        for capability_id, contract_version in release.declared_capabilities:
            definition = catalog.get(capability_id)
            if (
                definition is None
                or definition.contract_version != contract_version
            ):
                raise SuperExpertGrantError(
                    f"platform capability is unavailable: {capability_id}",
                )
        return SuperExpertGrantPreview(
            preview_id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            agent_id=agent_id,
            release_id=release.release_id,
            package_digest=release.content_digest,
            package_version=release.version,
            capability_digest=release.capability_digest,
            capabilities=release.declared_capabilities,
        )

    def cancel(self, preview: SuperExpertGrantPreview) -> None:
        del preview

    def grant_installation(
        self,
        preview: SuperExpertGrantPreview,
        *,
        administrator_id: str,
        authorization_source: Literal["administrator", "publisher"] = "administrator",
    ) -> SuperExpertGrant:
        grant = SuperExpertGrant(
            installation_id=uuid.uuid4().hex,
            tenant_id=preview.tenant_id,
            agent_id=preview.agent_id,
            release_id=preview.release_id,
            package_digest=preview.package_digest,
            package_version=preview.package_version,
            capability_digest=preview.capability_digest,
            capabilities=preview.capabilities,
            administrator_id=administrator_id,
            authorization_source=authorization_source,
        )
        with self._lock:
            document = self._read()
            if any(
                item.tenant_id == grant.tenant_id
                and item.agent_id == grant.agent_id
                and item.release_id == grant.release_id
                for item in document.grants
            ):
                raise SuperExpertGrantError(
                    "release installation is already granted",
                )
            document.grants.append(grant)
            self._write(document)
        return grant

    def get(self, installation_id: str) -> SuperExpertGrant | None:
        return next(
            (
                grant
                for grant in self.list_grants()
                if grant.installation_id == installation_id
            ),
            None,
        )

    def list_grants(self) -> list[SuperExpertGrant]:
        with self._lock:
            return list(self._read().grants)

    def authorize_capability(
        self,
        installation_id: str,
        capability: str,
        contract_version: str,
        *,
        tenant_id: str,
    ) -> AuthorizationDecision:
        grant = self.get(installation_id)
        allowed = bool(
            grant
            and grant.tenant_id == tenant_id
            and (capability, contract_version) in grant.capabilities,
        )
        return AuthorizationDecision(
            allowed=allowed,
            installation_id=installation_id,
            capability_id=capability,
            contract_version=contract_version,
            reason="granted" if allowed else "not_granted",
        )

    def is_release_granted(
        self,
        agent_id: str,
        release: SealedReleaseRecord,
        *,
        tenant_id: str,
    ) -> bool:
        return (
            self.find_release_grant(
                agent_id,
                release,
                tenant_id=tenant_id,
            )
            is not None
        )

    def find_release_grant(
        self,
        agent_id: str,
        release: SealedReleaseRecord,
        *,
        tenant_id: str,
    ) -> SuperExpertGrant | None:
        return next(
            (
                grant
                for grant in self.list_grants()
                if grant.tenant_id == tenant_id
                and grant.agent_id == agent_id
                and grant.release_id == release.release_id
                and grant.package_digest == release.content_digest
                and grant.package_version == release.version
                and grant.capability_digest == release.capability_digest
                and grant.capabilities == release.declared_capabilities
            ),
            None,
        )

    def _read(self) -> _GrantDocument:
        if not self.path.exists():
            return _GrantDocument()
        try:
            return _GrantDocument.model_validate_json(
                self.path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise SuperExpertGrantError("grant registry is invalid") from exc

    def _write(self, document: _GrantDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                document.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


def grant_installation(
    repository: SuperExpertGrantRepository,
    preview: SuperExpertGrantPreview,
    *,
    administrator_id: str,
) -> SuperExpertGrant:
    return repository.grant_installation(
        preview,
        administrator_id=administrator_id,
    )


def authorize_capability(
    repository: SuperExpertGrantRepository,
    installation_id: str,
    capability: str,
    contract_version: str,
    *,
    tenant_id: str,
) -> AuthorizationDecision:
    return repository.authorize_capability(
        installation_id,
        capability,
        contract_version,
        tenant_id=tenant_id,
    )
