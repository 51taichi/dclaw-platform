# -*- coding: utf-8 -*-
"""User-facing configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from ...config import load_config, save_config
from ...config.timezone import normalize_tz

router = APIRouter(prefix="/config", tags=["user-config"])


@router.get(
    "/user-timezone",
    summary="Get user timezone",
    description="Return the configured user IANA timezone",
)
async def get_user_timezone() -> dict:
    config = load_config()
    return {"timezone": config.user_timezone}


@router.put(
    "/user-timezone",
    summary="Update user timezone",
    description="Set the user IANA timezone",
)
async def put_user_timezone(
    body: dict = Body(..., description="Body with 'timezone' key"),
) -> dict:
    tz = body.get("timezone", "").strip()
    if not tz:
        raise HTTPException(status_code=400, detail="timezone is required")
    resolved = normalize_tz(tz)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid IANA timezone: {tz!r}",
        )
    config = load_config()
    config.user_timezone = resolved
    save_config(config)
    return {"timezone": resolved}
