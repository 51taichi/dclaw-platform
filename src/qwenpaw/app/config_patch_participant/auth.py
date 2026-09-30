"""Authentication for the narrow config-patch participant API."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


SERVICE_SECRET_HEADER = "X-DClaw-Config-Patch-Secret"
SERVICE_SECRET_ENV = "DCLAW_CONFIG_PATCH_INTERNAL_SECRET"


def require_config_patch_service(request: Request) -> None:
    """Require the dedicated service credential for internal participant calls."""
    expected = os.environ.get(SERVICE_SECRET_ENV, "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={"code": "CONFIG_PATCH_NOT_CONFIGURED"},
        )

    supplied = request.headers.get(SERVICE_SECRET_HEADER, "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_SERVICE_CREDENTIAL"},
        )

