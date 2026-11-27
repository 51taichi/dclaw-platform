# -*- coding: utf-8 -*-
"""Fail-closed payer resolution for background model executions."""
from __future__ import annotations

from typing import Any, Mapping

from ..storage.repos.user_repo import get_user_repository


class BillingPayerResolutionError(RuntimeError):
    """Raised when a user-triggered execution has no durable payer."""


def _normalized_user_id(value: Any) -> str:
    user_id = str(value or "").strip()
    if not user_id or not user_id.isdigit() or int(user_id) <= 0:
        raise BillingPayerResolutionError("billing payer is unavailable")
    return user_id


def _user_exists(user_id: str) -> bool:
    return get_user_repository().get_user_by_id(int(user_id)) is not None


def _existing_user(value: Any) -> str:
    user_id = _normalized_user_id(value)
    if not _user_exists(user_id):
        raise BillingPayerResolutionError("billing payer is unavailable")
    return user_id


def resolve_channel_payer(
    channel: str,
    external_user_id: str,
    channel_meta: Mapping[str, Any] | None,
) -> str:
    """Resolve an authenticated channel binding without trusting sender IDs."""
    if (
        not str(channel or "").strip()
        or not str(external_user_id or "").strip()
    ):
        raise BillingPayerResolutionError("channel identity is unavailable")
    meta = channel_meta or {}
    if meta.get("binding_authenticated") is not True:
        raise BillingPayerResolutionError("channel identity is not bound")
    return _existing_user(meta.get("bound_user_id"))


def resolve_job_payer(job: Any) -> str:
    """Resolve a cron owner; delivery targets never become implicit payers."""
    meta = getattr(job, "meta", None) or {}
    return _existing_user(meta.get("created_by_user_id"))


__all__ = [
    "BillingPayerResolutionError",
    "resolve_channel_payer",
    "resolve_job_payer",
]
