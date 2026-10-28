# -*- coding: utf-8 -*-
"""Authenticated client, device, package, credential, and DevKit APIs."""

from __future__ import annotations

import io
import hashlib
import json
import secrets
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any
import zipfile

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .business_identity import BusinessIdentityError, BusinessIdentityManager
from .credentials import CredentialBroker, CredentialError
from .developer_pack.archive import (
    build_archive as build_developer_pack_archive,
)
from .mcp_server import LocalExecutionMcp
from .packages import CapabilityPackageRegistry, PackageError
from .public_components import PublicComponentError, PublicComponentRegistry
from .service import LocalExecutionService
from .store import StateStore


PUBLIC_KEYS_RATE_LIMIT_PER_MINUTE = 60
PUBLIC_KEYS_RATE_LIMIT_MAX_CLIENTS = 4096


class _PublicKeysRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[str, deque[float]] = {}

    def _prune(self, cutoff: float) -> None:
        expired = [
            client
            for client, requests in self._requests.items()
            if not requests or requests[-1] <= cutoff
        ]
        for client in expired:
            self._requests.pop(client, None)

    def allow(self, client: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - 60.0
        with self._lock:
            if (
                client not in self._requests
                and len(self._requests) >= PUBLIC_KEYS_RATE_LIMIT_MAX_CLIENTS
            ):
                self._prune(cutoff)
                if len(self._requests) >= PUBLIC_KEYS_RATE_LIMIT_MAX_CLIENTS:
                    return False
            recent = self._requests.setdefault(client, deque())
            while recent and recent[0] <= cutoff:
                recent.popleft()
            if len(recent) >= PUBLIC_KEYS_RATE_LIMIT_PER_MINUTE:
                return False
            recent.append(current)
            return True


class PackageRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descriptor: dict[str, Any]
    signer_id: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=1, max_length=1024)


class PublicComponentRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descriptor: dict[str, Any]
    signer_id: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=1, max_length=1024)


COMPONENT_PLATFORMS = {
    "windows-x64": {"helper": "windows-helper", "status": "available"},
    "windows-arm64": {"helper": "windows-helper", "status": "reserved"},
    "macos-arm64": {"helper": "mac-helper", "status": "reserved"},
    "macos-x64": {"helper": "mac-helper", "status": "reserved"},
}


def _complete_component_registry(store: StateStore) -> dict[str, Any]:
    return {
        **store.get_public_component_registry(),
        "helper_platforms": COMPONENT_PLATFORMS,
    }


class CredentialBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=128)
    secret: dict[str, Any]
    scopes: list[str] = Field(min_length=1)
    agent_ids: list[str] = Field(default_factory=list)
    installation_ids: list[str] = Field(min_length=1)


class DeviceBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    force_pairing: bool = False


class BusinessServiceRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    developer_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)
    audience: str = Field(min_length=1, max_length=2048)
    allowed_domains: list[str] = Field(min_length=1, max_length=32)
    allowed_scopes: list[str] = Field(min_length=1, max_length=64)


class BusinessIdentityGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    release_id: str = Field(min_length=1, max_length=128)
    installation_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)
    audience: str = Field(min_length=1, max_length=2048)
    scopes: list[str] = Field(min_length=1, max_length=64)


class BusinessIdentityRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emergency: bool = False


class BusinessIdentityRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    tenant_id: str = Field(min_length=1, max_length=128)
    subject_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=512)


class BusinessIdentityVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertion: str = Field(min_length=1, max_length=8192)
    audience: str = Field(min_length=1, max_length=2048)
    installation_id: str = Field(min_length=1, max_length=128)
    release_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)
    required_scopes: list[str] = Field(min_length=1, max_length=64)


def _user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return str(user_id)


def _require_admin(request: Request) -> None:
    role = str(getattr(request.state, "role", "") or "")
    is_admin = bool(getattr(request.state, "is_admin", False))
    if role != "admin" and not is_admin:
        raise HTTPException(status_code=403, detail="administrator required")


def _developer_kit_archive(root: Path | None = None) -> tuple[bytes, str]:
    root = root or Path(__file__).parent / "devkit"
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    prefix = f"dclaw-super-agent-devkit-{version}"
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (
                not path.is_file()
                or "__pycache__" in relative.parts
                or "__MACOSX" in relative.parts
                or path.suffix == ".pyc"
                or path.name == ".DS_Store"
                or path.name.startswith("._")
            ):
                continue
            name = relative.as_posix()
            info = zipfile.ZipInfo(
                f"{prefix}/{name}",
                (2026, 10, 26, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o100755 if name in {
                "bootstrap.sh",
                "dclaw_agent_devkit.py",
            } else 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue(), version


def _register_developer_kit_routes(app: FastAPI) -> None:
    @app.get("/developer-kit")
    async def developer_kit_metadata() -> dict[str, Any]:
        archive, version = _developer_kit_archive()
        devkit_root = Path(__file__).parent / "devkit"
        return {
            "name": "dclaw-super-agent-devkit",
            "version": version,
            "download_path": "/api/super-agent-support/developer-kit/v1.zip",
            "sha256": hashlib.sha256(archive).hexdigest(),
            "server_source_required": False,
            "dependency_mode": "bundled-wheelhouse",
            "offline_bootstrap": True,
            "supported_python": ">=3.10,<3.14",
            "supported_platforms": [
                "linux-glibc-aarch64",
                "linux-glibc-x86_64",
                "macos-arm64",
                "macos-x86_64",
                "windows-x86_64",
            ],
            "requirements_lock_sha256": hashlib.sha256(
                (devkit_root / "requirements.lock").read_bytes(),
            ).hexdigest(),
            "wheelhouse_manifest_sha256": hashlib.sha256(
                (devkit_root / "CHECKSUMS.sha256").read_bytes(),
            ).hexdigest(),
        }

    @app.get("/developer-kit/v1.zip")
    async def download_developer_kit() -> Response:
        archive, version = _developer_kit_archive()
        return Response(
            archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    "attachment; filename="
                    f'"dclaw-super-agent-devkit-{version}.zip"'
                ),
            },
        )

    @app.get("/developer-pack")
    async def developer_pack_metadata() -> dict[str, Any]:
        archive, metadata = build_developer_pack_archive(Path(__file__).parent)
        return {
            **metadata,
            "download_path": "/api/super-agent-support/developer-pack/download",
            "content_sha256": hashlib.sha256(archive).hexdigest(),
            "offline": True,
            "supported_python": ">=3.10,<3.14",
            "supported_platforms": [
                "linux-glibc-aarch64",
                "linux-glibc-x86_64",
                "macos-arm64",
                "macos-x86_64",
                "windows-x86_64",
            ],
        }

    @app.get("/developer-pack/download")
    async def download_developer_pack() -> Response:
        archive, metadata = build_developer_pack_archive(Path(__file__).parent)
        return Response(
            archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    "attachment; filename="
                    f'"{metadata["archive_prefix"]}.zip"'
                ),
            },
        )


def create_app(
    *,
    store: StateStore,
    service: LocalExecutionService,
    mcp: LocalExecutionMcp,
    packages: CapabilityPackageRegistry,
    credentials: CredentialBroker,
    business_identity: BusinessIdentityManager | None = None,
    public_components: PublicComponentRegistry | None = None,
) -> FastAPI:
    # pylint: disable=too-many-statements
    app = FastAPI(
        title="DClaw Super Agent Support",
        docs_url=None,
        redoc_url=None,
    )
    app.mount("/mcp", mcp.app, name="local-execution-mcp")
    device_message_validator = Draft202012Validator(
        json.loads(
            (
                Path(__file__).parent
                / "schemas"
                / "device-message.schema.json"
            ).read_text(encoding="utf-8"),
        ),
    )
    public_keys_rate_limiter = _PublicKeysRateLimiter()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "plugin": "dclaw.super-agent-support",
            "version": "1.12.1",
            "protocols": {
                "local_execution": "1.2",
                "device": "2",
                "business_identity": "1",
                "public_components": "1",
            },
        }

    _register_developer_kit_routes(app)

    if business_identity is not None:

        @app.get("/business-identities/verification-keys")
        async def business_identity_verification_keys(
            request: Request,
        ) -> Response:
            client = request.client.host if request.client else "unknown"
            if not public_keys_rate_limiter.allow(client):
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60", "Cache-Control": "no-store"},
                )
            payload = business_identity.verification_keys()
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            etag = '"' + hashlib.sha256(encoded).hexdigest() + '"'
            headers = {
                "Cache-Control": "public, max-age=60, must-revalidate",
                "ETag": etag,
                "X-Content-Type-Options": "nosniff",
            }
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers=headers)
            return Response(
                encoded,
                media_type="application/json",
                headers=headers,
            )

        @app.post("/business-identities/assertions/verify")
        async def verify_business_identity_assertion(
            body: BusinessIdentityVerification,
        ) -> dict[str, Any]:
            try:
                claims = business_identity.verify_assertion(
                    body.assertion,
                    audience=body.audience,
                    installation_id=body.installation_id,
                    release_id=body.release_id,
                    agent_id=body.agent_id,
                    service_id=body.service_id,
                    required_scopes=body.required_scopes,
                )
            except BusinessIdentityError as exc:
                raise HTTPException(
                    status_code=401,
                    detail={"code": exc.code},
                ) from exc
            return {"active": True, "claims": claims}

        @app.post("/admin/business-identities/services")
        async def register_business_identity_service(
            body: BusinessServiceRegistration,
            request: Request,
        ) -> dict[str, Any]:
            _require_admin(request)
            try:
                return business_identity.register_service(
                    actor_id=_user_id(request),
                    **body.model_dump(),
                )
            except BusinessIdentityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"code": exc.code},
                ) from exc

        @app.post("/admin/business-identities/grants")
        async def grant_business_identity(
            body: BusinessIdentityGrant,
            request: Request,
        ) -> dict[str, Any]:
            _require_admin(request)
            try:
                return business_identity.grant_installation(
                    actor_id=_user_id(request),
                    **body.model_dump(),
                )
            except BusinessIdentityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"code": exc.code},
                ) from exc

        @app.post("/admin/business-identities/keys/rotate")
        async def rotate_business_identity_key(
            body: BusinessIdentityRotation,
            request: Request,
        ) -> dict[str, Any]:
            _require_admin(request)
            return business_identity.rotate_key(
                actor_id=_user_id(request),
                emergency=body.emergency,
            )

        @app.post("/admin/business-identities/revocations")
        async def revoke_business_identity(
            body: BusinessIdentityRevocation,
            request: Request,
        ) -> dict[str, Any]:
            _require_admin(request)
            try:
                return business_identity.revoke(
                    actor_id=_user_id(request),
                    **body.model_dump(),
                )
            except BusinessIdentityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"code": exc.code},
                ) from exc

        @app.get("/admin/business-identities/audit")
        async def business_identity_audit(
            request: Request,
            limit: int = 100,
        ) -> dict[str, Any]:
            _require_admin(request)
            try:
                return {"records": business_identity.audit_records(limit=limit)}
            except BusinessIdentityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"code": exc.code},
                ) from exc

    @app.get("/environment-status")
    async def environment_status(request: Request) -> dict[str, Any]:
        return await service.environment_status(
            user_id=_user_id(request),
            agent_protocol_version="2",
        )

    @app.post("/device-bootstrap")
    async def device_bootstrap(
        request: Request,
        body: DeviceBootstrap | None = None,
    ) -> dict[str, Any]:
        user_id = _user_id(request)
        known_device = (
            store.get_device_for_user(body.device_id, user_id)
            if body and body.device_id and not body.force_pairing
            else None
        )
        if known_device is not None:
            return {
                "paired": True,
                "device_id": known_device["device_id"],
                "pairing_code": None,
                "expires_in": 0,
                "websocket_path": "/api/super-agent-support/devices/connect",
            }
        return {
            "paired": False,
            "device_id": None,
            "pairing_code": store.create_pairing(user_id),
            "expires_in": 300,
            "websocket_path": "/api/super-agent-support/devices/connect",
        }

    @app.websocket("/devices/connect")
    async def connect_device(websocket: WebSocket) -> None:
        query = websocket.query_params
        device_id = str(query.get("device_id") or uuid.uuid4().hex)
        device_token = query.get("device_token")
        pairing_code = query.get("pairing_code")
        user_id: str | None = None
        issued_token: str | None = None
        if device_token:
            device = store.authenticate_device(device_id, device_token)
            if device is not None:
                user_id = str(device["user_id"])
        elif pairing_code:
            user_id = store.consume_pairing(pairing_code)
            if user_id:
                device_id = uuid.uuid4().hex
                issued_token = secrets.token_urlsafe(32)
        if not user_id:
            await websocket.close(
                code=4401,
                reason="device authentication failed",
            )
            return
        await websocket.accept()
        protocol_version = str(query.get("protocol_version") or "1")
        if protocol_version not in {"1", "2"}:
            protocol_version = "1"
        store.upsert_device(
            device_id=device_id,
            user_id=user_id,
            display_name=str(query.get("display_name") or "Windows device"),
            runner_version=str(query.get("runner_version") or "unknown"),
            protocol_version=protocol_version,
            platform=str(query.get("platform") or "windows-x64"),
            device_token=issued_token,
        )
        await service.attach(device_id, websocket)
        await websocket.send_json(
            {
                "type": "connection.ready",
                "protocol_version": protocol_version,
                "device_id": device_id,
                "device_token": issued_token,
            },
        )
        try:
            while True:
                message = await websocket.receive_json()
                if isinstance(message, dict):
                    errors = list(
                        device_message_validator.iter_errors(message),
                    )
                    if errors:
                        await websocket.send_json(
                            {
                                "type": "protocol.error",
                                "code": "INVALID_DEVICE_MESSAGE",
                            },
                        )
                        continue
                    await service.handle_device_message(
                        device_id,
                        user_id,
                        message,
                    )
        except WebSocketDisconnect:
            pass
        finally:
            await service.detach(device_id, websocket)

    @app.post("/capability-packages/register")
    async def register_package(
        body: PackageRegistration,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)
        try:
            packages.register(
                body.descriptor,
                signer_id=body.signer_id,
                signature=body.signature,
            )
        except PackageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "registered": True,
            "package_id": body.descriptor["package_id"],
            "package_version": body.descriptor["package_version"],
            "capability_id": body.descriptor["capability_id"],
        }

    @app.get("/capability-packages")
    async def list_packages(request: Request) -> dict[str, Any]:
        _require_admin(request)
        return {"packages": store.list_packages()}

    @app.get("/component-registry")
    async def get_component_registry(request: Request) -> dict[str, Any]:
        _user_id(request)
        return _complete_component_registry(store)

    @app.put(
        "/admin/component-registry/{component_id}/variants/{platform}",
    )
    async def set_component_registry_entry(
        component_id: str,
        platform: str,
        body: dict[str, Any],
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)
        try:
            registration = PublicComponentRegistration.model_validate(body)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="invalid public Component registration envelope",
            ) from exc
        if not component_id or len(component_id) > 128 or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in component_id
        ):
            raise HTTPException(status_code=422, detail="invalid component_id")
        if component_id[0] not in "abcdefghijklmnopqrstuvwxyz":
            raise HTTPException(status_code=422, detail="invalid component_id")
        if platform not in COMPONENT_PLATFORMS:
            raise HTTPException(status_code=422, detail="unsupported platform")
        if public_components is None:
            raise HTTPException(
                status_code=503,
                detail="public Component registry is not configured",
            )
        descriptor = dict(registration.descriptor)
        if (
            descriptor.get("component_id") != component_id
            or descriptor.get("platform") != platform
        ):
            raise HTTPException(
                status_code=422,
                detail="descriptor path identity mismatch",
            )
        try:
            return {
                **public_components.register(
                    descriptor,
                    signer_id=registration.signer_id,
                    signature=registration.signature,
                    updated_by=_user_id(request),
                ),
                "helper_platforms": COMPONENT_PLATFORMS,
            }
        except PublicComponentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/credentials")
    async def bind_credential(
        body: CredentialBinding,
        request: Request,
    ) -> dict[str, Any]:
        try:
            reference = credentials.bind(
                user_id=_user_id(request),
                provider=body.provider,
                secret=body.secret,
                scopes=body.scopes,
                agent_ids=body.agent_ids,
                installation_ids=body.installation_ids,
            )
        except CredentialError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "credential_ref": reference,
            "provider": body.provider,
            "scopes": body.scopes,
            "agent_ids": body.agent_ids,
            "installation_ids": body.installation_ids,
        }

    @app.delete("/credentials/{credential_ref}")
    async def revoke_credential(
        credential_ref: str,
        request: Request,
    ) -> dict[str, Any]:
        revoked = credentials.revoke(
            credential_ref,
            user_id=_user_id(request),
        )
        if not revoked:
            raise HTTPException(status_code=404, detail="credential not found")
        return {"revoked": True, "credential_ref": credential_ref}

    return app
