"""Authentication dependencies for the independent FastAPI application."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import AuthenticatedStaffToken
from .tokens import (
    ExpiredStaffTokenError,
    InvalidStaffTokenError,
    RevokedStaffTokenError,
    StaffTokenService,
)


ADMIN_SECRET_HEADER = "X-Config-Patch-Admin-Secret"
_bearer = HTTPBearer(auto_error=False)


def get_staff_token_service(request: Request) -> StaffTokenService:
    return request.app.state.staff_token_service


def require_internal_admin(request: Request) -> None:
    expected = request.app.state.config_patch_settings.admin_secret
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={"code": "ADMIN_AUTH_NOT_CONFIGURED"},
        )
    supplied = request.headers.get(ADMIN_SECRET_HEADER, "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_ADMIN_CREDENTIAL"},
        )


def require_staff_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    service: StaffTokenService = Depends(get_staff_token_service),
) -> AuthenticatedStaffToken:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "STAFF_TOKEN_REQUIRED"},
        )
    try:
        return service.authenticate(credentials.credentials)
    except ExpiredStaffTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "STAFF_TOKEN_EXPIRED"},
        ) from exc
    except RevokedStaffTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "STAFF_TOKEN_REVOKED"},
        ) from exc
    except InvalidStaffTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_STAFF_TOKEN"},
        ) from exc
