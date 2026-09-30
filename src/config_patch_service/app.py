"""Standalone FastAPI entrypoint for the configuration patch service."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime

import uvicorn
from fastapi import Depends, FastAPI

from . import SERVICE_NAME, SERVICE_VERSION
from .audit import AuditService
from .capabilities import CapabilityCatalog, CapabilityCatalogService
from .context import ConfigurationContextService
from .db import ConfigPatchDatabase
from .dependencies import require_staff_token
from .models import AuthenticatedStaffToken
from .routers.admin_tokens import router as admin_tokens_router
from .routers.staff_bots import router as staff_bots_router
from .settings import ConfigPatchSettings
from .tokens import StaffTokenService
from .upstreams.dclaw import DclawClient
from .upstreams.omnichannel import OmnichannelClient


def create_app(
    *,
    settings: ConfigPatchSettings | None = None,
    clock: Callable[[], datetime] | None = None,
    omnichannel_client: OmnichannelClient | None = None,
    dclaw_client: DclawClient | None = None,
    capability_catalog: CapabilityCatalogService | None = None,
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
    effective_omnichannel_client = omnichannel_client or OmnichannelClient(
        base_url=effective_settings.omnichannel_base_url,
        service_secret=effective_settings.omnichannel_service_secret,
    )
    effective_dclaw_client = dclaw_client or DclawClient(
        service_secret=effective_settings.dclaw_service_secret,
    )
    context_service = ConfigurationContextService(
        omnichannel=effective_omnichannel_client,
        dclaw=effective_dclaw_client,
    )
    catalog_service = capability_catalog or CapabilityCatalogService()
    catalog = catalog_service.load()

    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION)
    app.state.config_patch_settings = effective_settings
    app.state.config_patch_database = database
    app.state.config_patch_audit = audit
    app.state.staff_token_service = token_service
    app.state.configuration_context_service = context_service
    app.state.capability_catalog_service = catalog_service
    app.state.capability_catalog = catalog
    app.include_router(admin_tokens_router)
    app.include_router(staff_bots_router)

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

    @app.get("/staff/v1/capabilities")
    def capabilities(
        identity: AuthenticatedStaffToken = Depends(require_staff_token),
    ) -> CapabilityCatalog:
        audit.record(
            "staff.capabilities.read",
            token_id=identity.token_id,
            employee_name=identity.employee_name,
            result="success",
        )
        return catalog

    return app


def main() -> None:
    uvicorn.run(
        "config_patch_service.app:create_app",
        factory=True,
        host=os.environ.get("CONFIG_PATCH_HOST", "0.0.0.0"),
        port=int(os.environ.get("CONFIG_PATCH_PORT", "8788")),
    )
