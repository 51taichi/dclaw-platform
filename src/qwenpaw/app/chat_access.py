# -*- coding: utf-8 -*-
"""Shared chat ownership checks for user-facing APIs."""
from __future__ import annotations

from fastapi import HTTPException, Request

from .auth import is_auth_enabled
from .storage.repos.user_repo import get_user_repository


def current_user_id(request: Request) -> str:
    """Return the authenticated user id as a string."""
    state = getattr(request, "state", None)
    user_id = getattr(state, "user_id", None)
    if user_id is None:
        if not is_auth_enabled():
            return "0"
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(user_id)


def is_admin_request(request: Request) -> bool:
    """Whether the authenticated caller is an administrator."""
    state = getattr(request, "state", None)
    return getattr(state, "role", None) == "admin"


def get_chat_row_for_current_user(
    request: Request,
    chat_id: str | None,
    *,
    allow_admin: bool = False,
):
    """Return a chat row only when it belongs to the current user.

    ``chat_id`` may be either the public chat UUID or the session id. We return
    404 on ownership mismatch so callers cannot probe whether another user's
    chat exists.
    """
    if not chat_id:
        return None

    rows = get_user_repository().find_chat_access_rows(chat_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_id = current_user_id(request)
    for row in rows:
        if allow_admin and is_admin_request(request):
            return row
        if str(row["user_id"]) == user_id:
            return row

    raise HTTPException(status_code=404, detail="Chat not found")


def ensure_chat_access(
    request: Request,
    chat_id: str | None,
    *,
    allow_admin: bool = False,
):
    """Require the current user to own ``chat_id`` and return its DB row."""
    return get_chat_row_for_current_user(
        request,
        chat_id,
        allow_admin=allow_admin,
    )


def ensure_chat_ids_access(
    request: Request,
    chat_ids: list[str],
    *,
    allow_admin: bool = False,
) -> None:
    """Require access to every chat id in ``chat_ids``."""
    for chat_id in chat_ids:
        ensure_chat_access(request, chat_id, allow_admin=allow_admin)
