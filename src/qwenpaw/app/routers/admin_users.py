# -*- coding: utf-8 -*-
"""Admin Users management API endpoints."""
from __future__ import annotations

from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth import _hash_password
from ..billing.service import get_wallet_service
from ..storage.repos.user_repo import get_user_repository

router = APIRouter(prefix="/users", tags=["admin_users"])


class UserSpec(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("", response_model=List[UserSpec])
async def list_users():
    """List all registered users."""
    return [
        UserSpec(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            created_at=str(row["created_at"]),
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
    if get_user_repository().get_user_by_username(username):
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
        )
        # New users get an empty wallet. Trial credits are deliberately not
        # granted here because a username is not verified-mobile evidence.
        get_wallet_service().get_or_create_personal_wallet(row["id"])
        return UserSpec(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            created_at=str(row["created_at"]),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create user: {e}",
        )


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
        )
