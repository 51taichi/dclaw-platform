"""Owner-scoped self-service publication of globally visible Super Experts."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from qwenpaw.app.routers.sealed_agents import get_sealed_agent_service
from qwenpaw.app.sealed_agents.package import (
    MAX_PACKAGE_BYTES,
    SealedPackageError,
    validate_sealed_package,
)
from qwenpaw.app.sealed_agents.service import SealedAgentReleaseError
from qwenpaw.app.sealed_agents.standard_workspace import (
    StandardWorkspaceError,
    validate_standard_workspace,
)
from qwenpaw.config.config import AgentProfileRef
from qwenpaw.config.utils import load_config, save_config
from qwenpaw.constant import WORKING_DIR

from .package_handler import PublicSuperAgentPackageHandler
from .public_runtime import isolation_available as runtime_isolation_available
from .publishers import PublisherError, PublisherRepository
from .state_continuity import (
    StateContinuityError,
    preview_activation_continuity,
)


class SignerRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_key: str = Field(min_length=40, max_length=100)


def _actor(request: Request) -> tuple[str, str]:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return str(getattr(request.state, "tenant_id", None) or "local"), str(user_id)


class PublisherPublication:
    def __init__(
        self,
        repository: PublisherRepository,
        handler: PublicSuperAgentPackageHandler,
        state_root: Path,
        isolation_available: Callable[[], bool] | None = None,
    ) -> None:
        self.repository = repository
        self.handler = handler
        self.state_root = Path(state_root)
        self.isolation_available = isolation_available or runtime_isolation_available
        self._locks: dict[str, asyncio.Lock] = {}
        self.router = APIRouter()
        self._register_routes()

    def _owned_release(
        self, agent_id: str, release_id: str, tenant_id: str, user_id: str,
    ) -> Any:
        if self.repository.agent_owner(agent_id) != (tenant_id, user_id):
            raise HTTPException(status_code=404, detail="expert not found")
        record = get_sealed_agent_service().get_agent(agent_id)
        if record is None or record.deleted_at is not None:
            raise HTTPException(status_code=404, detail="expert not found")
        release = next(
            (item for item in record.releases if item.release_id == release_id),
            None,
        )
        if release is None or release.package_type != "super_expert_public":
            raise HTTPException(status_code=404, detail="release not found")
        if self.repository.signer_owner(release.signer_id) != (
            tenant_id, user_id,
        ):
            raise HTTPException(status_code=403, detail="release owner mismatch")
        return release

    async def _activate(
        self, request: Request, agent_id: str, release_id: str,
        tenant_id: str, user_id: str,
    ) -> dict[str, Any]:
        service = get_sealed_agent_service()
        release = self._owned_release(
            agent_id, release_id, tenant_id, user_id,
        )
        existing_grant = self.handler.grant_repository.find_release_grant(
            agent_id, release, tenant_id=tenant_id,
        )
        validation = await service.validate_release_runtime(
            agent_id, release_id,
        )
        if validation.status != "valid":
            raise HTTPException(
                status_code=422, detail={
                    "error": "expert runtime validation failed",
                    "release_id": release_id, "uploaded": True,
                    "granted": existing_grant is not None, "active": False,
                },
            )
        if existing_grant is None:
            try:
                preview = self.handler.preview_grant(
                    agent_id, release, tenant_id=tenant_id,
                )
                self.handler.grant_repository.grant_installation(
                    preview,
                    administrator_id=user_id,
                    authorization_source="publisher",
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={
                    "error": str(exc), "release_id": release_id,
                    "uploaded": True, "granted": False, "active": False,
                }) from exc
        try:
            runtime_root = service.prepare_runtime_workspace(
                agent_id, release_id,
            )
        except OSError as exc:
            raise HTTPException(
                status_code=422, detail={
                    "error": "expert runtime unavailable",
                    "release_id": release_id, "uploaded": True,
                    "granted": True, "active": False,
                },
            ) from exc
        state_root = Path(WORKING_DIR) / "workspace_runtime_state"
        state_root.mkdir(parents=True, exist_ok=True)
        current_record = service.get_agent(agent_id)
        target_grant = self.handler.grant_repository.find_release_grant(
            agent_id, release, tenant_id=tenant_id,
        )
        try:
            if current_record is None or target_grant is None:
                raise StateContinuityError("state_release_identity_mismatch")
            continuity = preview_activation_continuity(
                storage_root=state_root,
                sealed_root=Path(WORKING_DIR) / "sealed_agents",
                grants=self.handler.grant_repository,
                record=current_record,
                target_grant=target_grant,
            )
        except StateContinuityError as exc:
            raise HTTPException(status_code=422, detail={
                "error": "state continuity preflight failed",
                "category": exc.category,
                "release_id": release_id, "uploaded": True,
                "granted": True, "active": False,
            }) from exc
        config = load_config()
        previous_profile = config.agents.profiles.get(agent_id)
        previous_record = service.get_agent(agent_id)
        activated = False
        try:
            service.activate(agent_id, release_id, tenant_id=tenant_id)
            activated = True
            config.agents.profiles[agent_id] = AgentProfileRef(
                id=agent_id, workspace_dir=str(runtime_root), enabled=True,
            )
            save_config(config)
            manager = getattr(request.app.state, "multi_agent_manager", None)
            if manager is None:
                raise SealedAgentReleaseError("expert runtime is unavailable")
            loaded = (
                await manager.reload_agent(agent_id)
                if manager.is_agent_loaded(agent_id)
                else await manager.preload_agent(agent_id)
            )
            if not loaded:
                raise SealedAgentReleaseError("expert runtime validation failed")
        except Exception as exc:
            if activated and previous_record is not None:
                service.restore_agent_record(previous_record)
            if previous_profile is None:
                config.agents.profiles.pop(agent_id, None)
            else:
                config.agents.profiles[agent_id] = previous_profile
            save_config(config)
            manager = getattr(request.app.state, "multi_agent_manager", None)
            if manager is not None:
                try:
                    if previous_profile is None and manager.is_agent_loaded(agent_id):
                        await manager.stop_agent(agent_id)
                    elif previous_profile is not None:
                        await manager.reload_agent(agent_id)
                except Exception:
                    pass
            raise HTTPException(
                status_code=422,
                detail={
                    "error": (
                        str(exc) if isinstance(exc, SealedAgentReleaseError)
                        else "expert activation failed"
                    ),
                    "release_id": release_id, "uploaded": True,
                    "granted": True, "active": False,
                },
            ) from exc
        return {
            "agent_id": agent_id,
            "release_id": release_id,
            "version": release.version,
            "content_digest": release.content_digest,
            "capability_digest": release.capability_digest,
            "signer_id": release.signer_id,
            "state": "active",
            "visibility": "public",
            "state_continuity": continuity,
        }

    def _register_routes(self) -> None:
        @self.router.post("/signers")
        async def register_signer(
            body: SignerRegistration, request: Request,
        ) -> dict[str, str]:
            tenant_id, user_id = _actor(request)
            try:
                signer_id, _ = self.repository.register_signer(
                    tenant_id, user_id, body.public_key,
                )
            except PublisherError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"signer_id": signer_id, "status": "registered"}

        @self.router.get("/agents")
        async def list_owned_agents(request: Request) -> dict[str, Any]:
            tenant_id, user_id = _actor(request)
            return {"agents": [
                {
                    "agent_id": record.agent_id,
                    "active_release_id": record.active_release_id,
                    "name": record.name,
                }
                for record in get_sealed_agent_service().list_agents()
                if self.repository.agent_owner(record.agent_id)
                == (tenant_id, user_id)
            ]}

        @self.router.post("/releases")
        async def upload_release(
            request: Request, file: UploadFile = File(...),
        ) -> dict[str, Any]:
            tenant_id, user_id = _actor(request)
            if not self.isolation_available():
                raise HTTPException(
                    status_code=503, detail="runtime isolation unavailable",
                )
            data = await file.read(MAX_PACKAGE_BYTES + 1)
            if len(data) > MAX_PACKAGE_BYTES:
                raise HTTPException(status_code=413, detail="package too large")
            try:
                validated = validate_sealed_package(
                    data,
                    trusted_signers=self.handler.trusted_signers,
                    staging_root=self.state_root / "publisher-staging",
                )
            except SealedPackageError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            try:
                manifest = validated.manifest
                if manifest.package_type != "super_expert_public":
                    raise HTTPException(
                        status_code=422,
                        detail="super_expert_public package required",
                    )
                if self.repository.signer_owner(manifest.signer_id) != (
                    tenant_id, user_id,
                ):
                    raise HTTPException(
                        status_code=403, detail="signer owner mismatch",
                    )
                self.handler.validate_manifest(manifest)
                validate_standard_workspace(
                    manifest.agent_id, validated.extracted_root / "agent",
                )
                agent_id = manifest.agent_id
            except (ValueError, StandardWorkspaceError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            finally:
                shutil.rmtree(validated.extracted_root, ignore_errors=True)
            async with self._locks.setdefault(agent_id, asyncio.Lock()):
                service = get_sealed_agent_service()
                existing = service.get_agent(agent_id)
                owner = self.repository.agent_owner(agent_id)
                if existing is not None and (
                    existing.deleted_at is not None
                    or owner != (tenant_id, user_id)
                    or any(
                        item.package_type != "super_expert_public"
                        for item in existing.releases
                    )
                ):
                    raise HTTPException(status_code=409, detail="agent_id unavailable")
                if existing is None and agent_id in load_config().agents.profiles:
                    raise HTTPException(status_code=409, detail="agent_id unavailable")
                new_claim = False
                try:
                    new_claim = self.repository.claim_agent(
                        agent_id, tenant_id, user_id,
                    )
                    release = service.install(data)
                except (PublisherError, SealedAgentReleaseError) as exc:
                    if new_claim:
                        self.repository.release_new_claim(
                            agent_id, tenant_id, user_id,
                        )
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                return await self._activate(
                    request, agent_id, release.release_id, tenant_id, user_id,
                )

        @self.router.post("/agents/{agent_id}/releases/{release_id}/activate")
        async def retry_activation(
            agent_id: str, release_id: str, request: Request,
        ) -> dict[str, Any]:
            tenant_id, user_id = _actor(request)
            async with self._locks.setdefault(agent_id, asyncio.Lock()):
                return await self._activate(
                    request, agent_id, release_id, tenant_id, user_id,
                )
