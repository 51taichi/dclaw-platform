# -*- coding: utf-8 -*-
"""Authenticated client, device, package, credential, and DevKit APIs."""

from __future__ import annotations

import io
import hashlib
import json
import secrets
import uuid
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
from fastapi.responses import Response
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .credentials import CredentialBroker, CredentialError
from .developer_pack.archive import (
    build_archive as build_developer_pack_archive,
)
from .mcp_server import LocalExecutionMcp
from .packages import CapabilityPackageRegistry, PackageError
from .service import LocalExecutionService
from .store import StateStore


class PackageRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descriptor: dict[str, Any]
    signer_id: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=1, max_length=1024)


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


def _developer_kit_archive() -> tuple[bytes, str]:
    root = Path(__file__).parent / "devkit"
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    prefix = f"dclaw-super-agent-devkit-{version}"
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            archive.write(
                path,
                f"{prefix}/{path.relative_to(root).as_posix()}",
            )
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

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "plugin": "dclaw.super-agent-support",
            "version": "1.9.0",
            "protocols": {"local_execution": "1.1", "device": "2"},
        }

    _register_developer_kit_routes(app)

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
