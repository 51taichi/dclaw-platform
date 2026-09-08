# -*- coding: utf-8 -*-
"""Force outdated desktop builds to update without affecting browser clients."""
from __future__ import annotations

import json
import os
from pathlib import Path

from packaging.version import InvalidVersion, Version
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

DESKTOP_HEADERS = (
    "x-dclaw-desktop-brand",
    "x-dclaw-desktop-version",
    "x-dclaw-desktop-platform",
    "x-dclaw-desktop-arch",
)


def _latest_version() -> str | None:
    manifest = Path(
        os.environ.get("DCLAW_DESKTOP_LATEST_PATH", "/opt/dclaw-updates/latest.json")
    )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    value = payload.get("version")
    return value.strip() if isinstance(value, str) and value.strip() else None


class DesktopVersionGateMiddleware(BaseHTTPMiddleware):
    """Return 426 only for recognized, outdated Tauri desktop requests."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        values = {name: request.headers.get(name) for name in DESKTOP_HEADERS}
        if not any(values.values()):
            # Normal browser/Web client: deliberately outside this mechanism.
            return await call_next(request)
        if not all(values.values()):
            return JSONResponse({"detail": "Incomplete desktop client metadata"}, 400)

        expected_brand = os.environ.get("DCLAW_DESKTOP_BRAND_ID", "dclaw")
        if values["x-dclaw-desktop-brand"] != expected_brand:
            return JSONResponse({"detail": "Desktop client brand mismatch"}, 400)

        latest = _latest_version()
        if latest is None:
            return JSONResponse({"detail": "Desktop release manifest unavailable"}, 503)
        try:
            outdated = Version(values["x-dclaw-desktop-version"] or "") < Version(latest)
        except InvalidVersion:
            return JSONResponse({"detail": "Invalid desktop client version"}, 400)

        if outdated:
            return JSONResponse(
                {
                    "detail": "Desktop client update required",
                    "latest_version": latest,
                },
                status_code=426,
                headers={"X-DClaw-Latest-Version": latest},
            )
        return await call_next(request)
