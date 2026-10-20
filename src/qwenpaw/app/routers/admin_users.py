# -*- coding: utf-8 -*-
"""Admin Users management API endpoints."""
from __future__ import annotations

from typing import List
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import _hash_password
from ..billing.service import get_wallet_service
from ..storage.repos.user_repo import get_user_repository
from ..user_identity import normalize_cn_mobile

router = APIRouter(prefix="/users", tags=["admin_users"])


class UserSpec(BaseModel):
    id: int
    username: str
    role: str
    created_at: str
    display_name: str | None = None
    phone_number: str | None = None
    ai_customer_service_url: str | None = None


class CreateUserRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)
    role: str = "user"
    display_name: str | None = Field(default=None, max_length=100)
    phone_number: str | None = Field(default=None, max_length=32)
    ai_customer_service_url: str | None = Field(default=None, max_length=2048)


class ResetPasswordRequest(BaseModel):
    new_password: str


class AiCustomerServiceRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)


def _normalize_ai_customer_service_url(value: str | None) -> str | None:
    url = (value or "").strip()
    if not url:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="AI customer service URL must be a valid HTTPS URL",
        )
    return url


@router.get("", response_model=List[UserSpec])
async def list_users():
    """List all registered users."""
    return [
        UserSpec(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            created_at=str(row["created_at"]),
            display_name=row.get("display_name"),
            phone_number=row.get("phone_number_e164"),
            ai_customer_service_url=row.get("ai_customer_service_url"),
        )
        for row in get_user_repository().list_users()
    ]


@router.post("", response_model=UserSpec)
async def create_user(req: CreateUserRequest):
    """Create a new user account."""
    if not req.username.strip() or not req.password.strip():
        raise HTTPException(
            status_code=400,
            detail="Username and password are required",
        )

    if req.role not in ("admin", "user"):
        raise HTTPException(
            status_code=400,
            detail="Role must be 'admin' or 'user'",
        )

    # Check if username exists
    username = req.username.strip()
    display_name = req.display_name.strip() if req.display_name is not None else None
    try:
        phone_number = normalize_cn_mobile(req.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ai_customer_service_url = _normalize_ai_customer_service_url(
        req.ai_customer_service_url,
    )
    existing = get_user_repository().get_user_by_username(username)
    if existing:
        # Repair a prior user-created/wallet-failed attempt before returning
        # the stable duplicate-user response.
        get_wallet_service().get_or_create_personal_wallet(existing["id"])
        raise HTTPException(
            status_code=409,
            detail=f"Username '{req.username}' already exists",
        )

    pw_hash, salt = _hash_password(req.password)
    try:
        row = get_user_repository().create_user(
            username=username,
            password_hash=pw_hash,
            password_salt=salt,
            role=req.role,
            display_name=display_name,
            phone_number_e164=phone_number,
            ai_customer_service_url=ai_customer_service_url,
        )
        # New users get an empty wallet. Trial credits are deliberately not
        # granted here because a username is not verified-mobile evidence.
        get_wallet_service().get_or_create_personal_wallet(row["id"])
        return UserSpec(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            created_at=str(row["created_at"]),
            display_name=row.get("display_name"),
            phone_number=row.get("phone_number_e164"),
            ai_customer_service_url=row.get("ai_customer_service_url"),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create user: {e}",
        ) from e


@router.put("/{user_id}/password")
async def reset_password(user_id: int, req: ResetPasswordRequest):
    """Reset a user's password."""
    if not req.new_password.strip():
        raise HTTPException(
            status_code=400,
            detail="Password cannot be empty",
        )

    # Check if user exists
    if not get_user_repository().get_user_by_id(user_id):
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    pw_hash, salt = _hash_password(req.new_password)
    try:
        get_user_repository().update_user_password(user_id, pw_hash, salt)
        return {"success": True}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset password: {e}",
        ) from e


@router.put("/{user_id}/ai-customer-service", response_model=UserSpec)
async def update_ai_customer_service(
    user_id: int,
    req: AiCustomerServiceRequest,
):
    """Configure or remove the user's independent AI customer-service entry."""
    repo = get_user_repository()
    if not repo.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")

    url = _normalize_ai_customer_service_url(req.url)
    row = repo.update_user_ai_customer_service_url(user_id, url)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSpec(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        created_at=str(row["created_at"]),
        display_name=row.get("display_name"),
        phone_number=row.get("phone_number_e164"),
        ai_customer_service_url=row.get("ai_customer_service_url"),
    )


@router.delete("/{user_id}")
async def delete_user(user_id: int):
    """Delete a user and cascade delete their chats and connections."""
    # Check if user exists and prevent deleting the last admin
    repo = get_user_repository()
    row = repo.get_user_by_id(user_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if row["role"] == "admin":
        if repo.count_admins() <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last admin user",
            )

    try:
        repo.delete_user_cascade(user_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete user: {e}",
        ) from e
