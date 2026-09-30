"""Standalone FastAPI entrypoint for the configuration patch service."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime

import uvicorn
from fastapi import Depends, FastAPI

from . import SERVICE_NAME, SERVICE_VERSION
from .audit import AuditService
from .db import ConfigPatchDatabase
from .dependencies import require_staff_token
from .models import AuthenticatedStaffToken
from .routers.admin_tokens import router as admin_tokens_router
from .settings import ConfigPatchSettings
from .tokens import StaffTokenService


def create_app(
    *,
    settings: ConfigPatchSettings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    effective_settings = settings or ConfigPatchSettings.from_env()
    database = ConfigPatchDatabase(effective_settings.database_path)
    database.initialize()
    audit_kwargs = {"clock": clock} if clock is not None else {}
    audit = AuditService(database, **audit_kwargs)
    token_kwargs = {"clock": clock} if clock is not None else {}
    token_service = StaffTokenService(
        database,
        pepper=effective_settings.token_pepper,
        audit=audit,
        **token_kwargs,
    )

    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION)
    app.state.config_patch_settings = effective_settings
    app.state.config_patch_database = database
    app.state.config_patch_audit = audit
    app.state.staff_token_service = token_service
    app.include_router(admin_tokens_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
        }

    @app.get("/staff/v1/whoami", response_model=AuthenticatedStaffToken)
    def whoami(
        identity: AuthenticatedStaffToken = Depends(require_staff_token),
    ) -> AuthenticatedStaffToken:
        return identity

    return app


def main() -> None:
    uvicorn.run(
        "config_patch_service.app:create_app",
        factory=True,
        host=os.environ.get("CONFIG_PATCH_HOST", "0.0.0.0"),
        port=int(os.environ.get("CONFIG_PATCH_PORT", "8788")),
    )
