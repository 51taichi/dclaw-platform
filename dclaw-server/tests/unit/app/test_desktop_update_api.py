# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers import desktop as desktop_router
from qwenpaw.app.routers.desktop import router


@pytest.mark.asyncio
async def test_desktop_update_returns_domestic_download_url(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    monkeypatch.setattr(
        desktop_router,
        "load_desktop_index",
        lambda: {
            "product": "desktop",
            "platforms": {"win": {"latest": "desktop-win-1.1.9"}},
            "files": {
                "desktop-win-1.1.9": {
                    "version": "1.1.9",
                    "platform": "win",
                    "url": "/files/apps/desktop/win/DClaw-Setup-1.1.9.exe",
                    "sha256": "abc123",
                    "size_bytes": 123456789,
                    "release_notes": "本次更新内容",
                },
            },
        },
    )
    monkeypatch.setenv("DCLAW_DOWNLOAD_BASE_URL", "https://download.dclaw.cn")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/desktop/update?platform=win&version=1.1.8")

    assert response.status_code == 200
    assert response.json() == {
        "has_update": True,
        "version": "1.1.9",
        "platform": "win",
        "download_url": (
            "https://download.dclaw.cn/files/apps/desktop/win/"
            "DClaw-Setup-1.1.9.exe"
        ),
        "sha256": "abc123",
        "size_bytes": 123456789,
        "release_notes": "本次更新内容",
        "force": False,
    }


@pytest.mark.asyncio
async def test_desktop_update_reports_no_update_for_same_version(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    monkeypatch.setattr(
        desktop_router,
        "load_desktop_index",
        lambda: {
            "platforms": {"mac": {"latest": "desktop-mac-1.1.9"}},
            "files": {"desktop-mac-1.1.9": {"version": "1.1.9", "platform": "mac"}},
        },
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/desktop/update?platform=mac&version=1.1.9")

    assert response.status_code == 200
    assert response.json() == {
        "has_update": False,
        "version": "1.1.9",
        "platform": "mac",
        "download_url": "",
        "sha256": "",
        "size_bytes": 0,
        "release_notes": "",
        "force": False,
    }
