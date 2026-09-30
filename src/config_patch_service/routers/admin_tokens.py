"""Server-to-server employee token administration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import get_staff_token_service, require_internal_admin
from ..models import (
    CreateStaffTokenRequest,
    IssuedStaffToken,
    StaffTokenList,
    StaffTokenView,
)
from ..tokens import StaffTokenService


router = APIRouter(
    prefix="/internal/admin/v1/staff-tokens",
    tags=["config-patch-admin"],
    dependencies=[Depends(require_internal_admin)],
)


@router.post("", response_model=IssuedStaffToken, status_code=status.HTTP_201_CREATED)
def create_staff_token(
    body: CreateStaffTokenRequest,
    service: StaffTokenService = Depends(get_staff_token_service),
) -> IssuedStaffToken:
    return service.create(
        employee_name=body.employee_name,
        token_name=body.token_name,
        expires_at=body.expires_at,
    )


@router.get("", response_model=StaffTokenList)
def list_staff_tokens(
    service: StaffTokenService = Depends(get_staff_token_service),
) -> StaffTokenList:
    return StaffTokenList(tokens=service.list())


@router.post("/{token_id}/revoke", response_model=StaffTokenView)
def revoke_staff_token(
    token_id: str,
    service: StaffTokenService = Depends(get_staff_token_service),
) -> StaffTokenView:
    try:
        return service.revoke(token_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "STAFF_TOKEN_NOT_FOUND"},
        ) from exc


@router.post("/{token_id}/rotate", response_model=IssuedStaffToken)
def rotate_staff_token(
    token_id: str,
    service: StaffTokenService = Depends(get_staff_token_service),
) -> IssuedStaffToken:
    try:
        return service.rotate(token_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "STAFF_TOKEN_NOT_FOUND"},
        ) from exc
