"""Versioned platform-capability catalog and signed-manifest validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, TypeAlias

from qwenpaw.app.sealed_agents.package import (
    CapabilityDeclaration,
    SealedPackageManifest,
)
from qwenpaw.app.sealed_agents.signing import SuperExpertTrustStore

SuperExpertManifest: TypeAlias = SealedPackageManifest


class CapabilityManifestError(ValueError):
    """A public-safe failure in a signed super-expert capability declaration."""


@dataclass(frozen=True)
class PlatformCapabilityDefinition:
    capability_id: str
    contract_version: str
    group: str
    dependencies: tuple[str, ...] = ()


_HOST = (
    "agent.execute",
    "session.context",
    "runtime.trace",
    "runtime.complete",
    "runtime.fail",
)


def _definition(
    capability_id: str,
    group: str,
    *,
    dependencies: tuple[str, ...] = (),
) -> PlatformCapabilityDefinition:
    return PlatformCapabilityDefinition(
        capability_id=capability_id,
        contract_version="1",
        group=group,
        dependencies=dependencies,
    )


PLATFORM_CAPABILITY_CATALOG_V1 = {
    item.capability_id: item
    for item in (
        _definition("workspace.turn.orchestrate/1", "runtime", dependencies=_HOST),
        *(_definition(capability, "runtime_host") for capability in _HOST),
        _definition("card.create", "card"),
        _definition("card.update", "card", dependencies=("card.create",)),
        _definition("aigc.capabilities.list/1", "aigc"),
        _definition("interaction.capabilities.list/1", "interaction"),
        _definition("local.execution.session/1", "local_execution"),
        _definition(
            "interaction.card.create/1",
            "interaction",
            dependencies=("interaction.capabilities.list/1",),
        ),
        _definition(
            "interaction.card.cancel/1",
            "interaction",
            dependencies=("interaction.card.create/1",),
        ),
        _definition("aigc.workflow.capabilities.list/1", "aigc"),
        _definition(
            "aigc.workflow.create/1",
            "aigc",
            dependencies=("aigc.workflow.capabilities.list/1",),
        ),
        _definition("aigc.task.create", "aigc"),
        _definition("aigc.task.create/2", "aigc"),
        _definition("aigc.task.resume", "aigc", dependencies=("aigc.task.create",)),
        _definition("aigc.task.cancel", "aigc", dependencies=("aigc.task.create",)),
        _definition("aigc.guide.update", "aigc", dependencies=("aigc.task.create",)),
        _definition("aigc.asset.submit", "aigc", dependencies=("aigc.task.create",)),
        _definition("aigc.review.complete", "aigc", dependencies=("aigc.task.create",)),
    )
}


def _as_payload(value: Mapping[str, Any] | SealedPackageManifest) -> dict[str, Any]:
    if isinstance(value, SealedPackageManifest):
        return value.model_dump(mode="json")
    return dict(value)


def compute_capability_set_digest(
    value: Mapping[str, Any] | SealedPackageManifest,
) -> str:
    """Digest every field that defines the package's platform authority."""
    payload = _as_payload(value)
    declarations = []
    for item in payload.get("capabilities", ()):
        if isinstance(item, CapabilityDeclaration):
            item = item.model_dump(mode="json")
        declarations.append(
            {
                "capability_id": item["capability_id"],
                "contract_version": item["contract_version"],
            },
        )
    authority = {
        "package_type": payload.get("package_type"),
        "orchestration": payload.get("orchestration"),
        "platform_contract_versions": payload.get("platform_contract_versions", {}),
        "capabilities": sorted(declarations, key=lambda item: item["capability_id"]),
    }
    encoded = json.dumps(
        authority,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_super_expert_manifest(
    package: SealedPackageManifest,
    trust_store: SuperExpertTrustStore,
) -> SuperExpertManifest:
    """Validate official provenance and the package-specific capability closure."""
    try:
        package.validate_supported_contract()
    except ValueError as exc:
        raise CapabilityManifestError(str(exc)) from exc
    if package.package_type != "super_expert":
        raise CapabilityManifestError("package is not a super expert")
    if not trust_store.is_official(package.signer_id):
        raise CapabilityManifestError("super expert signer is not official")
    if package.capability_digest != compute_capability_set_digest(package):
        raise CapabilityManifestError("capability digest mismatch")

    try:
        declarations = tuple(
            item
            if isinstance(item, CapabilityDeclaration)
            else CapabilityDeclaration.model_validate(item)
            for item in package.capabilities
        )
    except Exception as exc:
        raise CapabilityManifestError("invalid capability declaration") from exc
    by_id = {item.capability_id: item for item in declarations}
    if len(by_id) != len(declarations):
        raise CapabilityManifestError("duplicate capability declaration")
    for capability_id, declaration in by_id.items():
        definition = PLATFORM_CAPABILITY_CATALOG_V1.get(capability_id)
        if definition is None:
            raise CapabilityManifestError(f"unknown capability: {capability_id}")
        if declaration.contract_version != definition.contract_version:
            raise CapabilityManifestError(
                f"unsupported capability version: {capability_id}",
            )
        missing = set(definition.dependencies) - set(by_id)
        if missing:
            raise CapabilityManifestError(
                f"missing capability dependency: {sorted(missing)[0]}",
            )

    orchestration = package.orchestration
    if orchestration is None or orchestration.capability_id not in by_id:
        raise CapabilityManifestError("orchestration capability is not declared")
    if set(orchestration.required_host_capabilities) != set(_HOST):
        raise CapabilityManifestError("required host capability set is incomplete")
    for capability_id in orchestration.required_host_capabilities:
        if capability_id not in by_id:
            raise CapabilityManifestError(
                f"missing host capability declaration: {capability_id}",
            )

    used_groups = {
        PLATFORM_CAPABILITY_CATALOG_V1[item.capability_id].group
        for item in declarations
    }
    for group in used_groups:
        if package.platform_contract_versions.get(group) != "1":
            raise CapabilityManifestError(
                f"unsupported platform contract version: {group}",
            )
    return package
