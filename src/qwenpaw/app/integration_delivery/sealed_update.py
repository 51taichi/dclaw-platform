# -*- coding: utf-8 -*-
"""Transparent signed-release adapter for sealed and super-expert Agents."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.version import InvalidVersion, Version

from ...config.config import AgentProfileRef
from ...config.utils import load_config, save_config
from ...constant import SECRET_DIR
from ..sealed_agents.package import (
    SealedPackageManifest,
    build_signed_package_bytes,
)
from ..sealed_agents.service import SealedAgentService
from ..super_experts.capabilities import validate_super_expert_manifest
from .update import (
    AgentApplyReceipt,
    DeliveryBundleError,
    ParsedDeliveryBundle,
    _source_digest,
)


class SealedDeliveryError(DeliveryBundleError):
    """A sealed Agent cannot be safely updated through the delivery adapter."""


def _service() -> SealedAgentService:
    from ..routers.sealed_agents import get_sealed_agent_service

    return get_sealed_agent_service()


def _load_signer(
    path: Path,
    service: SealedAgentService | Any,
    *,
    super_expert: bool,
) -> tuple[str, Ed25519PrivateKey]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        signer_id = str(payload["signerId"])
        raw = base64.b64decode(payload["privateKey"], validate=True)
        private = Ed25519PrivateKey.from_private_bytes(raw)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise SealedDeliveryError(
            "sealed delivery signing material is unavailable",
        ) from exc
    trusted = service.trusted_signers.get(signer_id)
    if trusted is None:
        raise SealedDeliveryError(
            "sealed delivery trusted signer is unavailable",
        )
    encoding = serialization.Encoding.Raw
    public_format = serialization.PublicFormat.Raw
    if private.public_key().public_bytes(
        encoding,
        public_format,
    ) != trusted.public_bytes(
        encoding,
        public_format,
    ):
        raise SealedDeliveryError(
            "sealed delivery trusted signer does not match",
        )
    if super_expert and not service.super_expert_trust_store.is_official(
        signer_id,
    ):
        raise SealedDeliveryError(
            "sealed delivery trusted signer is not official",
        )
    return signer_id, private


def _next_version(record: Any) -> str:
    try:
        current = max(Version(item.version) for item in record.releases)
    except (InvalidVersion, ValueError) as exc:
        raise SealedDeliveryError("sealed Agent version is invalid") from exc
    return f"{current.major}.{current.minor}.{current.micro + 1}"


def _active_manifest(
    service: SealedAgentService | Any,
    agent_id: str,
) -> tuple[Any, dict[str, Any]]:
    record = service.get_agent(agent_id)
    active = record.active_release if record is not None else None
    if record is None or not record.enabled or active is None:
        raise SealedDeliveryError("sealed Agent active release is unavailable")
    path = service.release_root(agent_id, active.release_id) / "manifest.json"
    try:
        manifest = SealedPackageManifest.model_validate_json(
            path.read_text(encoding="utf-8"),
        ).model_dump(mode="json")
    except (OSError, ValueError) as exc:
        raise SealedDeliveryError(
            "sealed Agent manifest is unavailable",
        ) from exc
    if manifest["agent_id"] != agent_id:
        raise SealedDeliveryError("sealed Agent identity mismatch")
    return record, manifest


def _validate_release(
    service: SealedAgentService | Any,
    agent_id: str,
    release_id: str,
) -> None:
    try:
        validation = asyncio.run(
            service.validate_release_runtime(agent_id, release_id),
        )
    except RuntimeError as exc:
        raise SealedDeliveryError(
            "sealed Agent runtime validation failed",
        ) from exc
    if validation.status != "valid":
        raise SealedDeliveryError("sealed Agent runtime validation failed")


def _activate(
    service: SealedAgentService | Any,
    agent_id: str,
    release_id: str,
    *,
    tenant_id: str,
    activate_runtime: Callable[[str], Any] | None,
) -> Path:
    _validate_release(service, agent_id, release_id)
    try:
        runtime_root = service.prepare_runtime_workspace(agent_id, release_id)
        if activate_runtime is not None:
            activate_runtime(release_id)
        else:
            service.activate(agent_id, release_id, tenant_id=tenant_id)
            config = load_config()
            config.agents.profiles[agent_id] = AgentProfileRef(
                id=agent_id,
                workspace_dir=str(runtime_root),
                enabled=True,
            )
            save_config(config)
    except Exception as exc:
        raise SealedDeliveryError("sealed Agent activation failed") from exc
    return Path(runtime_root)


def apply_sealed_agent_source(
    bundle: ParsedDeliveryBundle,
    operation_id: str,
    *,
    service: SealedAgentService | Any | None = None,
    signer_path: Path | None = None,
    tenant_id: str = "local",
    activate_runtime: Callable[[str], Any] | None = None,
) -> AgentApplyReceipt:
    """Sign, validate and activate an immutable release for an Agent."""

    sealed_service = service or _service()
    record, manifest = _active_manifest(sealed_service, bundle.agent_id)
    active = record.active_release
    active_root = (
        sealed_service.release_root(bundle.agent_id, active.release_id)
        / "agent"
    )
    before_digest = _source_digest(active_root)
    package_type = str(manifest["package_type"])
    signer_id, private_key = _load_signer(
        Path(
            signer_path
            or Path(SECRET_DIR) / "integration_delivery_signer.json",
        ),
        sealed_service,
        super_expert=package_type == "super_expert",
    )
    next_manifest = dict(manifest)
    next_manifest.update(
        {
            "version": _next_version(record),
            "signer_id": signer_id,
        },
    )
    if package_type == "super_expert":
        validate_super_expert_manifest(
            SealedPackageManifest.model_validate(next_manifest),
            sealed_service.super_expert_trust_store,
        )
    package = build_signed_package_bytes(
        next_manifest,
        bundle.agent_files,
        private_key,
    )
    release = sealed_service.install(package)
    if package_type == "super_expert":
        sealed_service.grant_installation(
            bundle.agent_id,
            release.release_id,
            tenant_id=tenant_id,
            administrator_id="integration-delivery",
        )
    try:
        runtime_root = _activate(
            sealed_service,
            bundle.agent_id,
            release.release_id,
            tenant_id=tenant_id,
            activate_runtime=activate_runtime,
        )
    except Exception:
        if (
            sealed_service.get_agent(bundle.agent_id).active_release_id
            != active.release_id
        ):
            try:
                _activate(
                    sealed_service,
                    bundle.agent_id,
                    active.release_id,
                    tenant_id=tenant_id,
                    activate_runtime=activate_runtime,
                )
            except Exception:
                pass
        raise
    return AgentApplyReceipt(
        operation_id=operation_id,
        agent_id=bundle.agent_id,
        agent_digest_before=before_digest,
        agent_digest_after=bundle.agent_digest,
        workspace_dir=runtime_root,
        previous_release_id=active.release_id,
        applied_release_id=release.release_id,
    )


def validate_sealed_agent_source(
    bundle: ParsedDeliveryBundle,
    *,
    service: SealedAgentService | Any | None = None,
    signer_path: Path | None = None,
) -> None:
    """Validate signing and retained declarations without installing."""

    sealed_service = service or _service()
    record, manifest = _active_manifest(sealed_service, bundle.agent_id)
    package_type = str(manifest["package_type"])
    signer_id, private_key = _load_signer(
        Path(
            signer_path
            or Path(SECRET_DIR) / "integration_delivery_signer.json",
        ),
        sealed_service,
        super_expert=package_type == "super_expert",
    )
    next_manifest = dict(manifest)
    next_manifest.update(
        {
            "version": _next_version(record),
            "signer_id": signer_id,
        },
    )
    if package_type == "super_expert":
        validate_super_expert_manifest(
            SealedPackageManifest.model_validate(next_manifest),
            sealed_service.super_expert_trust_store,
        )
    build_signed_package_bytes(next_manifest, bundle.agent_files, private_key)


def restore_sealed_agent_source(
    receipt: AgentApplyReceipt,
    *,
    service: SealedAgentService | Any | None = None,
    tenant_id: str = "local",
    activate_runtime: Callable[[str], Any] | None = None,
) -> None:
    """Reactivate the immutable release that preceded this delivery update."""

    if receipt.previous_release_id is None:
        raise SealedDeliveryError(
            "sealed Agent recovery release is unavailable",
        )
    _activate(
        service or _service(),
        receipt.agent_id,
        receipt.previous_release_id,
        tenant_id=tenant_id,
        activate_runtime=activate_runtime,
    )
