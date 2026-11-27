# -*- coding: utf-8 -*-
"""Desktop client update endpoints."""
from __future__ import annotations

import json
import os
from typing import Any, Literal
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel

router = APIRouter(prefix="/desktop", tags=["desktop"])

DEFAULT_DOWNLOAD_BASE_URL = "https://download.dclaw.cn"
DEFAULT_INDEX_URL = (
    f"{DEFAULT_DOWNLOAD_BASE_URL}/metadata/apps/desktop/index.json"
)
BLOCKED_UPDATE_HOSTS = (
    "github.com",
    "githubusercontent.com",
    "amazonaws.com",
    "cloudflare.com",
    "cloudflareinsights.com",
)


class DesktopUpdateResponse(BaseModel):
    has_update: bool
    version: str
    platform: Literal["win", "mac"]
    download_url: str = ""
    sha256: str = ""
    size_bytes: int = 0
    release_notes: str = ""
    force: bool = False


def _reject_foreign_update_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in BLOCKED_UPDATE_HOSTS):
        raise HTTPException(
            status_code=502,
            detail="Desktop update source must use the domestic release channel.",
        )


def _version(value: str) -> Version:
    try:
        return Version(value)
    except InvalidVersion:
        # Current packaged builds may use values like 1.1.8b1. packaging can
        # parse that, so reaching here means the client sent an unusable value.
        raise HTTPException(status_code=400, detail="Invalid desktop version") from None


def load_desktop_index() -> dict[str, Any]:
    index_url = os.environ.get("DCLAW_UPDATE_INDEX_URL", DEFAULT_INDEX_URL)
    _reject_foreign_update_host(index_url)
    req = Request(index_url, headers={"User-Agent": "DClawDesktopUpdate/1.0"})
    try:
        with urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load desktop update index: {exc}",
        ) from exc


def _build_download_url(raw_url: str) -> str:
    if raw_url.startswith(("http://", "https://")):
        _reject_foreign_update_host(raw_url)
        return raw_url
    base_url = os.environ.get("DCLAW_DOWNLOAD_BASE_URL", DEFAULT_DOWNLOAD_BASE_URL)
    _reject_foreign_update_host(base_url)
    return urljoin(base_url.rstrip("/") + "/", raw_url.lstrip("/"))


def _latest_file(index: dict[str, Any], platform: str) -> dict[str, Any] | None:
    platforms = index.get("platforms", {})
    files = index.get("files", {})
    latest_id = platforms.get(platform, {}).get("latest", "")
    if not latest_id:
        return None
    latest = files.get(latest_id)
    return latest if isinstance(latest, dict) else None


@router.get("/update", response_model=DesktopUpdateResponse)
async def check_desktop_update(
    platform: Literal["win", "mac"] = Query(...),
    version: str = Query(..., min_length=1),
) -> DesktopUpdateResponse:
    index = load_desktop_index()
    latest = _latest_file(index, platform)
    if not latest:
        return DesktopUpdateResponse(
            has_update=False,
            version=version,
            platform=platform,
        )

    latest_version = str(latest.get("version") or version)
    if _version(latest_version) <= _version(version):
        return DesktopUpdateResponse(
            has_update=False,
            version=latest_version,
            platform=platform,
        )

    return DesktopUpdateResponse(
        has_update=True,
        version=latest_version,
        platform=platform,
        download_url=_build_download_url(str(latest.get("url") or "")),
        sha256=str(latest.get("sha256") or ""),
        size_bytes=int(latest.get("size_bytes") or 0),
        release_notes=str(latest.get("release_notes") or ""),
        force=bool(latest.get("force") or False),
    )
